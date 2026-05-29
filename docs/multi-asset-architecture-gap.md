# 多标的（标的池）场景适配性分析

> 围绕"是否能基于标的池做交易决策"对 TradingAgents-CN 当前架构的诊断。
> 论文（[arXiv:2412.20138](https://arxiv.org/pdf/2412.20138)）回测基于**单标的**，
> 真实交易场景往往面对**标的池**（数十到数百只候选），二者的核心需求差异巨大。

---

## 一、当前仓库的核心假设：单标的 + 单时点

代码层面的硬约束：

| 位置 | 约束 |
|---|---|
| `tradingagents/agents/utils/agent_states.py:54` | `company_of_interest: Annotated[str, ...]` — 状态字段是 `str` 不是 `List[str]` |
| `tradingagents/graph/propagation.py:64` | `create_initial_state(ticker: str, ...)` — 入口只接受单个 ticker |
| `tradingagents/graph/trading_graph.py:685` | `propagate(company_name, trade_date, ...)` — 主入口同样 |

整个 LangGraph 工作流的设计前提就是 **"单标的全栈深度分析"**。论文里的回测也是这个范式。

---

## 二、现状下"标的池场景"的支持情况

仓库**部分**支持，但只是浅层支持：

### 已有

| 模块 | 作用 |
|---|---|
| `app/services/stock_pool_service.py` | Top120 + 持仓拼成池子（用于数据同步，**非决策**） |
| `app/services/screening_service.py` 等 4 个筛选服务 | 基于 DSL 做技术/基本面筛选（**纯规则**，不走 agent） |
| `app/routers/analysis.py:776-868` 批量分析接口 | 池子里每只股票**独立跑一遍 LangGraph**，并发上限 10 |

### 实际工作模式

```
[Screener 选出候选池] → [对每只独立调用 propagate()] → [得到 N 份独立报告]
                            ↑ 各 graph 之间完全不通信
```

**这是"批量重复单标的分析"，不是"标的池决策"。**

---

## 三、"标的池决策"真正需要什么 — 当前架构都缺

| 标的池决策的核心需求 | 当前架构状态 |
|---|---|
| **横截面排序**（哪些更值得买） | 缺失。每只股票独立给买/卖/持，不分高下 |
| **组合相关性约束**（同行业避免叠加） | 缺失。两只都"强烈买入"且高相关时无识别 |
| **资金分配 / 仓位优化** | 缺失。Trader 给单票仓位，无组合层 |
| **共享市场状态判断** | 缺失。每只股票独立判断 regime，10 只可能给出 10 种宏观判断 |
| **行业 / 风格因子归因** | 缺失。无因子分解 |
| **池子轮动 / 调仓** | 缺失。每次都是从零分析 |
| **风险预算 / VaR / 回撤约束** | 缺失。Risk Manager 只看单票风险 |
| **执行约束**（流动性、容量、滑点） | 缺失 |

---

## 四、单标的范式直接跑池子会出什么问题

### 1. 信号不可比

不同分析师在不同股票上给的"置信度 0.8"含义不同：A 股票的 0.8 可能是"基本面强劲"，B 股票的 0.8 可能是"消息驱动"。
**没有横向校准**就无法决定先买哪只。

### 2. Prompt 偏置直接放大到组合层

`risk_manager.py:35` "只有……才选择持有，避免作为后备" —— 单标的下逼模型表态。
**池子场景下，"持有 / 弃权"才是正确动作**（用资金买更好的标的），但 prompt 把弃权当兜底惩罚。
→ 直接结果：**所有标的都倾向买入**，资金分散，丧失选股 alpha。

### 3. Memory 跨标的污染

5 份 ChromaDB memory（bull/bear/trader/judge/risk）按"情境相似度"召回，**不区分标的**。
分析"贵州茅台"时可能召回"五粮液"的过去决策（行业相似），但两者基本面差异已经很大。
**单标的范式时是"经验"，池子范式时是"传染"**。

### 4. 成本呈线性 N 倍

单只 ≈ 14 个 LLM 调用。池子 100 只 ≈ 1400 次调用。即使并发 10，仍然是 100 倍单标的成本，且没有任何信息共享带来的 token 节省。

### 5. 时序连续性丢失

池子场景下 "上周已分析过" 的信号应该被复用或增量更新。
当前每次 `propagate()` 都从零开始，**不读上次 state**（除了 memory）。

---

## 五、改造成池子系统的三种路径

按工作量从小到大：

### Level 1：保持单标的 graph，外加协调层（改造小）

```
[Universe Filter] (基于因子/规则筛池)
    ↓
[Single-Stock Graph × N]（现有 graph，并发跑）
    ↓
[Cross-Sectional Ranker]  ← 新增
    ↓
[Portfolio Constructor]   ← 新增（仓位/相关性/约束）
    ↓
[Execution]
```

- **Cross-Sectional Ranker**：把 N 份单标的报告**统一打分体系下排序**（需先解决信号不可比问题）
- **Portfolio Constructor**：基于排序 + 协方差矩阵 + 资金约束求解（凯利或 mean-variance）

**改造成本**：中。现有 graph 不动，外面套两层。
**天花板**：被单标的 graph 决定。

### Level 2：图内引入跨标的节点（改造大）

让 LangGraph state 持有 `tickers: List[str]` 和 `cross_sectional_signals`，新增节点：

- **Macro Regime Node**（一次判断市场状态，所有标的共享）
- **Sector Allocator**（行业层先决定权重，再分到个股）
- **Cross-Stock Bull/Bear**（同时给多只股票排序，而非孤立判断）
- **Portfolio Risk Manager**（替代当前个股 Risk Manager）

**改造成本**：高。state 重设计，节点重写，prompt 大量改动，memory schema 推倒。
**天花板**：真正的池子系统，但 LLM 在数值优化上能力不足，体感收益未必匹配工作量。

### Level 3：拒绝 LLM 做组合层（务实路线，**推荐**）

LLM 不擅长**多变量数值优化**（仓位求解、协方差估计）。
更现实的方案：

- **LLM 层**：单标的方向 + 概率 + 失效条件（保留现有架构，按 prompt 优化建议改）
- **代码层**：Black-Litterman / Risk Parity / 因子模型做组合配置

LLM 输出的"主观概率 + 不确定区间"作为先验喂给数值优化器。这是当前业界混合架构的主流做法。

---

## 六、结论

| 问题 | 答复 |
|---|---|
| 当前仓库**适合基于标的池决策**吗？ | **不适合**——只是支持"批量执行单标的分析" |
| 论文回测能复现到池子场景吗？ | 不能直接复现。论文场景是"假设我决定交易这只股票，方向判断准不准"；池子场景是"在 100 只里选哪几只" |
| 改造可行吗？ | 可行，但需要新增"组合层"——LLM 做不了的部分（数值优化）应交给代码 |
| 改造前要先做什么？ | 先解决**信号不可比**（A.2 概率赋权）和**强制表态**（A.1 允许弃权）。否则池子层永远拿不到可比信号 |

---

## 七、建议的实操路径

1. **先**完成 `prompt-optimization-findings.md` 里的 P0 项：
   - A.1 删除强制表态 prompt（允许弃权）
   - A.2 改 advocacy → steelman + 概率赋权
   - Trader 改 deep
   - 输出 schema 加 `horizon / invalidation / stop_loss / position_size`

   完成后，单标的输出从"模糊建议"变成**可比的概率信号**。

2. **再**走 Level 3 路线：LLM 单标的 + 代码层组合优化。
   - 新增 `app/services/portfolio/` 层，承担 ranker + constructor 职责
   - LangGraph 不动，仍然是单标的工作流
   - 由 portfolio 层批量调用 + 横向打分 + 数值化求解仓位

3. **跳过 Level 2**（LLM 直接管池子）：投入产出比低，且 LLM 在数值优化上不可信。

---

## 八、需要新增的关键模块（如果走 Level 3）

```
app/services/portfolio/
├── ranker.py          # 横截面排序：把 N 份单标的报告校准到统一打分体系
├── correlator.py      # 相关性矩阵估计（基于 daily returns）
├── allocator.py       # 资金分配：凯利 / Risk Parity / Black-Litterman
├── constraints.py     # 行业上限 / 单票上限 / 流动性约束 / 换手率约束
└── rebalancer.py      # 调仓决策：当前持仓 vs 目标持仓
```

依赖前置项（必须在 LLM 层先完成）：

- 单标的输出包含 `prob_up_in_horizon`（在指定时间窗口上涨概率）
- 单标的输出包含 `expected_return_distribution`（不只是点估计）
- 单标的输出允许 `action="abstain"`
- Memory 召回区分 ticker / 行业 / 时间窗口

否则 portfolio 层拿不到可用先验，回到"垃圾入垃圾出"。
