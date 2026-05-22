# TradingAgents 工作流优化设计文档

**日期**：2026-05-22  
**范围**：LangGraph 工作流业务效果优化，共 4 个独立改动

---

## 背景

当前工作流存在以下问题，影响业务效果和运行成本：

1. 辩论阶段每次 LLM 调用都重复传递 4 份完整分析报告，Token 浪费严重
2. 辩论终止条件只看轮次计数，双方已收敛时仍继续辩论
3. Trader 节点的 user context 是英文，与中文系统提示混用
4. 目标价格职责不清晰，Research Manager 强制要求具体数值导致锚定效应

---

## 优化 1：辩论综合摘要节点（原优化点 2）

### 问题

Bull/Bear/Risky/Safe/Neutral 五个辩论节点，以及 Research Manager 和 Risk Manager，每次调用都把 4 份原始报告完整塞入 Prompt。单次 Prompt 可达 40,000+ 字符，整个流程中 4 份报告被重复传递约 8-10 次。

### 方案

在图结构中，最后一个分析师的 `Msg Clear` 节点之后、`Bull Researcher` 之前，插入新节点 `Report Summarizer`。

**节点职责**：
- 读取 `market_report`、`sentiment_report`、`news_report`、`fundamentals_report`
- 用 `quick_thinking_llm` 生成一份综合摘要，上限 2000 字
- 写入新状态字段 `combined_report_summary`

**摘要 Prompt 要求**：
- 保留关键财务数据（价格、估值、财务指标）
- 保留核心风险因素和机会点
- 保留市场情绪倾向
- 不做投资建议，只做信息整合

**下游节点改动**：
- Bull/Bear/Risky/Safe/Neutral/Research Manager/Risk Manager 的 Prompt 中，将 4 份报告替换为 `combined_report_summary`
- 原始 4 份报告字段保留在状态中，不删除（供日志和反思使用）

**状态变更**：
- `AgentState` 新增字段：`combined_report_summary: Annotated[str, "Combined summary of all analyst reports"]`

**图结构变更**（`setup.py`）：
```
... → Msg Clear {last_analyst} → Report Summarizer → Bull Researcher → ...
```

---

## 优化 2：辩论提前终止（原优化点 5）

### 问题

`conditional_logic.py` 的 `should_continue_debate` 和 `should_continue_risk_analysis` 只检查 `count >= max_count`。当双方立场已经趋于一致时，仍会继续辩论到上限，浪费 Token 且不提升决策质量。

### 方案

在两个条件函数中，计数检查之前加收敛判断。

**收敛判断逻辑**：
- 仅在 `count >= 2`（至少双方各发言一次）后才触发判断
- 用 `quick_thinking_llm` 分析最近两轮发言（`current_response` 和对方最新回应）
- Prompt 要求模型只返回 `YES` 或 `NO`，判断双方立场是否已趋于一致
- 如果返回 `YES`，直接路由到 Research Manager / Risk Judge
- 如果返回 `NO` 或调用失败，继续正常计数逻辑

**ConditionalLogic 构造函数变更**：
- 新增参数 `convergence_llm`（可选），用于收敛判断
- 如果未传入，跳过收敛判断，保持原有纯计数行为（向后兼容）

**收敛判断 Prompt**（投资辩论）：
```
以下是看涨分析师和看跌分析师的最新发言。
判断双方立场是否已经趋于一致（都倾向同一方向，或分歧已不显著）。
只回答 YES 或 NO，不要解释。

看涨方最新发言：{bull_response}
看跌方最新发言：{bear_response}
```

**收敛判断 Prompt**（风险讨论）：
```
以下是三位风险分析师的最新发言。
判断三方立场是否已经趋于一致（分歧已不显著）。
只回答 YES 或 NO，不要解释。

激进分析师：{risky_response}
保守分析师：{safe_response}
中性分析师：{neutral_response}
```

---

## 优化 3：Trader context 中文化（原优化点 6）

### 问题

`trader.py:53-56` 的 user context 是英文，与中文系统提示混用，对中文优化模型（通义千问、DeepSeek 等）可能影响输出质量和格式一致性。

### 方案

直接将 context 内容改为中文，语义保持不变：

**改前**：
```python
context = {
    "role": "user",
    "content": f"Based on a comprehensive analysis by a team of analysts, here is an investment plan tailored for {company_name}. This plan incorporates insights from current technical market trends, macroeconomic indicators, and social media sentiment. Use this plan as a foundation for evaluating your next trading decision.\n\nProposed Investment Plan: {investment_plan}\n\nLeverage these insights to make an informed and strategic decision.",
}
```

**改后**：
```python
context = {
    "role": "user",
    "content": f"以下是分析师团队为 {company_name} 制定的投资计划，综合了技术面、宏观经济指标和市场情绪分析。请以此为基础，结合你的独立判断做出交易决策。\n\n投资计划：{investment_plan}\n\n请注意：投资计划中的目标价格仅供参考，请基于你自己的分析独立给出目标价位。",
}
```

注意最后一句同时承担优化 4 的部分职责（告知 Trader 独立计算价格）。

---

## 优化 4：目标价格职责分层（原优化点 7）

### 问题

Research Manager 被要求"强制提供具体目标价格"，这个价格会传给 Trader，形成锚定效应，影响后续独立判断。目标价格的精确计算应由最终决策节点（Risk Manager）负责。

### 方案

**Research Manager（`research_manager.py`）**：
- 将"必须提供具体目标价格"改为"提供参考价格区间"
- 删除"不允许说无法确定"的强制要求
- 改为："基于辩论和报告，给出合理的价格参考区间（如 XX-XX 元），无需精确到具体数值"

**Trader（`trader.py`）**：
- 在 context 中加入"Research Manager 的价格仅供参考，请独立计算"（已在优化 3 的改动中包含）
- 系统提示中保留"必须提供具体目标价位"的要求不变

**Risk Manager（`risk_manager.py` 标准版和 structured 版）**：
- 在 prompt 的"交付成果"部分，新增明确要求：
  ```
  - 具体目标价格：必须给出明确的数值或区间（如 XX 元或 XX-XX 元），不允许回复"无法确定"
  ```
- structured 版的 `TradeDecision.target_price` 字段描述已有"无法确定时为 null"，改为"必须提供具体数值，不允许为 null"

---

## 文件改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `tradingagents/agents/utils/agent_states.py` | 新增字段 | `combined_report_summary` |
| `tradingagents/graph/setup.py` | 新增节点和边 | `Report Summarizer` 节点，插入图结构 |
| `tradingagents/graph/conditional_logic.py` | 修改逻辑 | 两个条件函数加收敛判断，构造函数加 `convergence_llm` 参数 |
| `tradingagents/graph/trading_graph.py` | 传参变更 | `ConditionalLogic` 初始化时传入 `convergence_llm` |
| `tradingagents/agents/researchers/bull_researcher.py` | 修改 Prompt | 用 `combined_report_summary` 替换 4 份报告 |
| `tradingagents/agents/researchers/bear_researcher.py` | 修改 Prompt | 同上 |
| `tradingagents/agents/risk_mgmt/aggresive_debator.py` | 修改 Prompt | 同上 |
| `tradingagents/agents/risk_mgmt/conservative_debator.py` | 修改 Prompt | 同上 |
| `tradingagents/agents/risk_mgmt/neutral_debator.py` | 修改 Prompt | 同上 |
| `tradingagents/agents/managers/research_manager.py` | 修改 Prompt | 目标价格改为参考区间 |
| `tradingagents/agents/managers/risk_manager.py` | 修改 Prompt | 新增强制目标价格要求（标准版和 structured 版） |
| `tradingagents/agents/utils/trade_decision.py` | 修改字段描述 | `target_price` 改为必填 |
| `tradingagents/agents/trader/trader.py` | 修改 context | 英文改中文，加独立计算价格说明 |

新增文件：
- `tradingagents/agents/summarizer/report_summarizer.py`（Report Summarizer 节点实现）

---

## 向后兼容性

- `combined_report_summary` 字段为新增，不影响现有状态读取
- `ConditionalLogic` 的 `convergence_llm` 参数为可选，不传时行为与现在完全一致
- 所有原始报告字段（`market_report` 等）保留，不删除
