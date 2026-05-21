# 工作流优化设计文档

**日期**：2026-05-21  
**涉及问题**：问题4（Risk Manager 字段错误）、问题5（SignalProcessor 二次 LLM 解析）、问题7（公司名称重复查询）  
**状态**：待实现

---

## 背景

TradingAgents-CN 的 LangGraph 工作流在代码审查中发现三个影响业务效果的问题：

- **问题4**：Risk Manager 读取了错误的 state 字段，导致 Trader 节点的输出被完全忽略
- **问题5**：SignalProcessor 对 Risk Judge 的输出进行二次 LLM 解析，引入不确定性和额外成本
- **问题7**：公司名称查询逻辑在 bull/bear researcher 中重复实现，每次分析至少发起 2 次 API 调用

---

## 问题4：Risk Manager 读取错误字段

### 根因

`risk_manager.py:17` 读取的是 `state["investment_plan"]`（Research Manager 的宏观建议），而非 `state["trader_investment_plan"]`（Trader 生成的具体交易计划，含目标价位、置信度、风险评分）。

工作流数据流：
```
Research Manager → investment_plan（宏观投资建议）
Trader           → trader_investment_plan（具体交易计划，含目标价）
Risk Manager     → 应读 trader_investment_plan，实际读 investment_plan  ← bug
```

### 改动方案

**仅改一行**，文件：`tradingagents/agents/managers/risk_manager.py`

```python
# 改前（第17行）
trader_plan = state["investment_plan"]

# 改后
trader_plan = state["trader_investment_plan"]
```

prompt 中的变量引用 `{trader_plan}` 不变，语义自动正确。

### 验证标准

Risk Manager 的 prompt 日志中 `{trader_plan}` 包含目标价位、置信度、风险评分等 Trader 输出的具体内容，而非 Research Manager 的宏观文字。

---

## 问题7：公司名称重复查询

### 根因

`bull_researcher.py` 和 `bear_researcher.py` 各自定义了完全相同的 `_get_company_name()` 内部函数，每次节点执行都发起 API 调用。对于 A 股，每次分析至少调用 2 次 `get_china_stock_info_unified()`。

### 改动方案

**方案：将公司名称缓存到 AgentState，Propagator 初始化时查询一次。**

#### 1. `tradingagents/agents/utils/agent_states.py`

`AgentState` 增加字段：

```python
company_name: Annotated[str, "Human-readable company name resolved from ticker"]
```

#### 2. `tradingagents/graph/propagation.py`

`create_initial_state()` 中增加查询逻辑，提取为模块级函数 `_resolve_company_name(ticker)`：

- A 股（6位数字）：调用 `get_china_stock_info_unified()`，解析 `股票名称:` 字段
- 港股（含 `.HK`）：调用 `get_hk_company_name_improved()`
- 美股：使用映射表（AAPL→苹果公司 等），未命中则返回 `美股{ticker}`
- 任何异常：fallback 返回 ticker 本身

查询结果写入初始 state 的 `company_name` 字段。

#### 3. `tradingagents/agents/researchers/bull_researcher.py`

- 删除内部 `_get_company_name()` 函数（约 40 行）
- 改为读取 `state["company_name"]`

#### 4. `tradingagents/agents/researchers/bear_researcher.py`

同 bull_researcher，删除重复函数，读取 `state["company_name"]`。

### 验证标准

日志中公司名称查询（`get_china_stock_info_unified` / `get_hk_company_name_improved`）只在 Propagator 初始化阶段出现一次，bull/bear researcher 节点不再有该调用。

---

## 问题5：SignalProcessor 二次 LLM 解析

### 根因

Risk Judge 输出自由文本 → SignalProcessor 再用 LLM 解析成 JSON。两次 LLM 调用，且第二次解析可能失败，触发多层 fallback，最终 confidence/risk_score 退化为硬编码的 0.7/0.5。

### 改动方案

**运行时检测 + 双路径**：支持 structured output 的 provider 直接输出结构化结果，不支持的 provider 保持现有 SignalProcessor 路径不变。

#### 1. 新增 `tradingagents/agents/utils/trade_decision.py`

定义共享输出模型：

```python
from pydantic import BaseModel, Field
from typing import Optional

class TradeDecision(BaseModel):
    action: str = Field(description="买入、持有或卖出之一")
    target_price: Optional[float] = Field(default=None, description="目标价格数值，无法确定时为null")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0, description="0-1之间的置信度")
    risk_score: float = Field(default=0.5, ge=0.0, le=1.0, description="0-1之间的风险评分")
    reasoning: str = Field(description="决策理由的中文摘要")
```

#### 2. `tradingagents/graph/trading_graph.py`

在 `__init__` 末尾，LLM 创建完成后，执行一次探测：

```python
self._supports_structured_output = self._probe_structured_output(self.deep_thinking_llm)
```

`_probe_structured_output()` 实现：

```python
def _probe_structured_output(self, llm) -> bool:
    try:
        llm.with_structured_output(TradeDecision)
        return True
    except (NotImplementedError, AttributeError):
        return False
```

注意：`with_structured_output()` 只是构造绑定对象，**不发起网络请求**，无额外成本。

将 `_supports_structured_output` 传入 `GraphSetup`。

#### 3. `tradingagents/graph/setup.py`

根据标志选择 risk_manager_node 的创建方式：

```python
if self.supports_structured_output:
    risk_manager_node = create_risk_manager_structured(
        self.deep_thinking_llm, self.risk_manager_memory
    )
else:
    risk_manager_node = create_risk_manager(
        self.deep_thinking_llm, self.risk_manager_memory
    )
```

#### 4. `tradingagents/agents/managers/risk_manager.py`

新增 `create_risk_manager_structured()` 函数，与现有 `create_risk_manager()` 共用同一个 prompt，区别：

- 使用 `llm.with_structured_output(TradeDecision)` 绑定 LLM
- 直接将返回的 `TradeDecision` 对象转为 dict
- 将结构化结果写入 `structured_trade_decision` state 字段
- `final_trade_decision` 仍写入 JSON 字符串（保持 state 完整性，供日志和反思使用）

#### 5. `tradingagents/agents/utils/agent_states.py`

增加可选字段：

```python
structured_trade_decision: Annotated[
    Optional[dict], "Structured decision dict, populated when provider supports structured output"
]
```

#### 6. `tradingagents/graph/trading_graph.py` — `propagate()` 方法

读取决策时优先用结构化字段，同时补上进度回调（修复现有 bug）：

```python
# 在 process_signal 调用前后补上进度回调
if progress_callback:
    progress_callback("📡 信号处理")

if final_state.get("structured_trade_decision"):
    decision = final_state["structured_trade_decision"]
else:
    decision = self.process_signal(final_state["final_trade_decision"], company_name)

decision['model_info'] = model_info
```

### 附：进度计算影响分析

`tracker.py:173` 中 `📡 信号处理` 步骤（weight=0.04）在现有代码里本来就未被正确触发——SignalProcessor 不是 LangGraph 节点，`_send_progress_update` 感知不到它。本次改动在 `propagate()` 中补上显式调用，**顺手修复了这个已有 bug**，两条路径（structured/fallback）均会触发该进度更新。

### 验证标准

- OpenAI / Anthropic / Google provider：日志中不出现 `[SignalProcessor] 处理信号` 的 LLM 调用，`structured_trade_decision` 字段有值
- 不支持 structured output 的 provider：行为与现在完全一致，SignalProcessor 正常工作
- 所有 provider：`decision` dict 的键（`action`, `target_price`, `confidence`, `risk_score`, `reasoning`, `model_info`）与改动前一致，`analysis_service.py` 无需修改

---

## 改动文件汇总

| 文件 | 改动类型 | 涉及问题 |
|------|----------|----------|
| `tradingagents/agents/managers/risk_manager.py` | 修改1行 + 新增函数 | 问题4、问题5 |
| `tradingagents/agents/utils/agent_states.py` | 新增2个字段 | 问题5、问题7 |
| `tradingagents/agents/utils/trade_decision.py` | 新增文件 | 问题5 |
| `tradingagents/graph/trading_graph.py` | 新增探测方法 + 修改propagate() | 问题5 |
| `tradingagents/graph/setup.py` | 修改risk_manager_node创建逻辑 | 问题5 |
| `tradingagents/graph/propagation.py` | 新增_resolve_company_name() + 修改create_initial_state() | 问题7 |
| `tradingagents/agents/researchers/bull_researcher.py` | 删除重复函数，读state字段 | 问题7 |
| `tradingagents/agents/researchers/bear_researcher.py` | 删除重复函数，读state字段 | 问题7 |

---

## 实现顺序建议

1. **问题4**（1行改动，独立，风险最低，先验证效果）
2. **问题7**（state schema 变更，需同步改4个文件，但逻辑简单）
3. **问题5**（依赖问题7的 state schema 变更完成后进行，改动最复杂）
