# Prompt 优化发现报告

> 围绕**高胜率、高收益**目标，对 TradingAgents-CN 当前所有 LangGraph 节点 prompt 的系统性审查。
> 审查覆盖：market / fundamentals / news / social 4 个分析师，bull / bear 2 个研究员，
> research_manager，trader，risky / safe / neutral 3 个风险分析师，risk_manager。

---

## 一、系统层先决问题（不只是 prompt）

### 1. 没有反馈闭环 — 所有"优化"都是盲调

- 系统能产出 `action / target_price`，但无回测、无 PnL 跟踪、无胜率统计模块。
- ChromaDB 里 5 份 memory（bull/bear/trader/judge/risk）召回的是"过去类似情境的建议"，**没有"那次决策对不对"的标签**。错误经验被反复强化。
- `risk_manager.py:148` 重试全失败时硬编码返回"持有 + 完整中性理由"，**没有标识位**，下游若入 memory 就是污染源。

> 胜率优化的前提是先能测量胜率，对应 CLAUDE.md Rule 9（测试验证 intent）层面的缺失。

### 2. 决策输出 schema 信息不足

`TradeDecision` 只有 `action / target_price / confidence / risk_score / reasoning`。缺：

- **盈亏比 R:R**：没有止损价、没有"如果错了亏多少 vs 对了赚多少"。即便方向胜率 60%，R:R = 1:2 仍然亏钱。
- **仓位建议**（凯利分数 / 风险敞口）：confidence=0.8 和 0.6 在仓位上应天差地别，现在等同。
- **预期持有期 horizon**：日内 / 周级 / 月级混在一起，目标价无意义。
- **失效条件 invalidation**：什么信号出现就退出？没有。

### 3. 市场状态盲（Regime Blind）

所有股票、所有时点用同一组 prompt 和同一套分析师顺序（market→social→news→fundamentals）。但牛市看动量/情绪，熊市看基本面/估值，震荡市看技术面/套利。
建议入口加 **Regime Classifier** 节点，路由到不同的分析师配置和 prompt 变体。

### 4. 数据层默认值激进

- `default_config.py:21-23`：`online_tools=false`、`realtime_data=false` 默认 → 用陈数据决策直接拉低胜率。
- `conditional_logic.py:225` fundamentals `max_tool_calls=1`，其他分析师是 3。基本面工具一次拿不全数据就被强制结束，是当前最薄弱环节。
- 默认 `gpt-4o-mini` + `o4-mini` 是省钱档，复杂金融推理掉得严重，尤其 Research Manager / Risk Judge 这种 deep_think 节点。

### 5. 结构性缺陷

- **单标的单时点**：没有跨标的强弱排序、时间序列连续追踪、组合相关性约束。**胜率提升的最大杠杆来自"选股"而非"判涨跌"**。
- **报告无冲突检测**：Summarizer 把 4 份报告拼接，没有"基本面看空 + 新闻面看多"如何处理。冲突场景往往是 alpha 所在。
- **风险辩论顺序固定**：Risky → Safe → Neutral 循环，Neutral 在 Risk Judge 前发言，**最近因偏置（recency bias）**会让 Neutral 论点权重虚高。

---

## 二、Prompt 层全局反模式（影响最大）

### A.1 强制表态产生幻觉决策（出现在 5+ 节点）

| 文件 | 反模式原文 |
|---|---|
| `risk_manager.py:35` | "只有在有具体论据强烈支持时才选择持有，而不是作为后备" |
| `risk_manager.py:46` | "不允许回复'无法确定'或'需要更多信息'" |
| `trader.py:94` | "绝对不允许说'无法确定目标价'或'需要更多信息'" |
| `trader.py:70` | "**必须提供具体的目标价位，不允许设置为null或空值**" |
| `fundamentals_analyst.py:206` | "不允许回复'无法确定价位'" |
| `news_analyst.py:140` | "不允许回复'无法评估影响'" |

**问题**：金融市场最重要的能力之一是承认不确定。强制 LLM 在数据不足时给具体数字 = 训练它编造。

**修复**：把"必须给具体数字"改成"必须给**带置信度的数字 + 触发条件**"：

```
- 若数据充分（至少 5 项关键指标可获取），给出目标价 + 置信度 0.6-0.9
- 若数据不足，给出目标价 + 置信度 0.3-0.5 + 明确标注"低置信"
- 允许输出 action="弃权"，但必须说明触发哪些 abstain 条件
```

### A.2 Advocacy 模式（律师 vs 真理）— 4 个辩论节点

| 文件 | 反模式用词 |
|---|---|
| `bull_researcher.py:51` | "建立**强有力**的论证"、"**反驳看跌论点**"、"**说明为什么看涨观点更有说服力**" |
| `bear_researcher.py:46` | "**论证不投资**的理由"、"**揭露弱点**" |
| `aggresive_debator.py:32` | "**积极倡导**高回报"、"**质疑和批评**保守立场" |
| `conservative_debator.py:33` | "**积极反驳**激进和中性分析师" |

**问题**：用词指令角色"找证据支持自己 + 攻击对方"——辩论赛思维而非分析师思维。每个角色都把弱论据包装得很强，Manager 看到的是噪声水平相近的对立陈述。

**修复**：改成 **steelman + 概率赋权**：

```
你是看涨方分析师。任务不是赢辩论，是诚实评估。

输出必须包含三部分：
1. 看涨论据：列出 3-5 条证据，每条标注：
   - 证据强度（强/中/弱），依据是什么数据
   - 这个证据反过来想，最强反驳是什么
2. 主观概率：你认为标的在 [horizon] 内上涨 X% 以上的概率（0-1，理由）
3. 你方观点的"如果错了"信号：什么数据出现就承认看错？
```

Bear 同理；Risky / Safe 同理。Manager 拿到的是**校准过的概率**和**触发条件**，而不是相互攻击的修辞。

### A.3 Memory 召回未标注成败但 prompt 让"从错误中学习"

`research_manager.py:39` 与 `risk_manager.py:39` 用 `past_memory_str` 做 RAG，召回"过去类似情境的决策建议"。Prompt 写"从过去错误中学习"——但召回字符串里**根本没有错误标注**。等于持续强化历史决策模式。

**修复**（对应系统级反馈闭环）：召回应改为：

```
{past_memory_str}（每条都附实际后续 N 日收益、是否止损、决策准确性标记）
```

短期 workaround：prompt 至少要显式提示 LLM "这些只是相似情境，不一定都是好决策，请独立判断"。

---

## 三、各节点具体 Prompt 问题

### B.1 市场分析师 — 输出格式过度规定

文件：`tradingagents/agents/analysts/market_analyst.py:170-471`

预设 7 节模板（基本信息 / MA / MACD / RSI / BOLL / 趋势 / 投资建议），且 `analysis_prompt`（L358-471）里**第二次**给了一个更长的模板（共 100+ 行格式指令）。

**问题**：
- 强迫 LLM 必须分析 MA+MACD+RSI+BOLL **四个**指标。如果某只股票真正关键的是成交量异动或趋势线突破，LLM 也得编凑全四节。
- "报告长度不少于 800 字"——指标不显著时被迫填字数 = 噪音。
- "**给出止损位**"和"**突破买入价 / 跌破卖出价**"在分析师阶段就硬性要求，这本是 Trader / Risk Manager 的工作；分析师强行回答会把噪声带进决策链。

**修复**：把"必须包含全部 4 个指标"改成"**仅报告有显著信号的指标**（背离/交叉/突破），无信号写 'N/A 该指标当前无明显信号'"，并删除"≥800 字"硬约束。

### B.2 基本面分析师 — Prompt 充满恐吓性大写

文件：`tradingagents/agents/analysts/fundamentals_analyst.py:184-237`

```
⚠️ 绝对强制要求：你必须调用工具获取真实数据！不允许任何假设或编造！
🔴 立即调用 get_stock_fundamentals_unified 工具
🚫 严格禁止：- 不允许说'我将调用工具' ...
现在立即开始调用工具！不要说任何其他话！
```

`system_prompt` 又重复一遍。`news_analyst.py:157-176` 也是同样模式。

**问题**：
- 大量大写恐吓 + 重复指令对前沿模型基本无效，反而占用上下文（Risk Manager 上次 prompt 长度就是性能瓶颈）。
- 这种模式说明开发者在**绕过模型偏好用 prompt 强行改行为**——通常是工具描述或 schema 没写清楚。应回头修工具，不是堆大写。

**修复**：删掉所有 🚫🔴⚠️ 重复禁令，改成一句清晰的工作流：

```
工作流：
1. 若 messages 中无 ToolMessage，调用 get_stock_fundamentals_unified(ticker, ...)
2. 若已有 ToolMessage，基于工具结果生成报告，不再调用
```

把强制性放在**工具的 description 字段**和**条件路由**里执行（已有 `should_continue_fundamentals` 计数器机制）。

### B.3 货币 / 公司名 prompt 反复出现，本质是数据层缺陷

每个 agent prompt 都重复"货币是 ¥/$、公司名是 X、不要混淆"。出现至少 7 次。

**根因**：传给 LLM 的工具结果里没把 `currency` 和 `company_name` 作为结构化字段强约束。
**修工具输出 schema 比修 prompt 高效**——一次到位，所有 agent 受益。

### B.4 风险辩论 prompt — 三方都在"攻击"，没人"综合"

文件：
- `tradingagents/agents/risk_mgmt/aggresive_debator.py`
- `tradingagents/agents/risk_mgmt/conservative_debator.py`
- `tradingagents/agents/risk_mgmt/neutral_debator.py`

Risky / Safe / Neutral 三个 prompt 完全对称，都写"反驳/质疑/挑战其他两方"。结果：

- Neutral 在 `neutral_debator.py:36` 被定义为"评估上行下行风险"——但因为整个模板套路是"反驳"，Neutral 实际会**反驳两边**而不是综合。
- 三人轮流发言，每人都在防御，Risk Judge 看到的是 3 段对抗性独白，没有共识基础。

**修复**：改 Neutral 为**仲裁角色**（不是第三方观点）：

```
你是风险综合分析师。前置：Risky 和 Safe 已发言。
任务：
1. 列出双方一致的事实（不仅是观点）
2. 列出真正的分歧点
3. 对每个分歧，给出在何种条件下倾向哪一方
4. 输出建议的仓位区间和止损区间（不是 buy/sell 决策）
```

Risk Judge 拿到的就是**已结构化的分歧清单 + 条件**，决策质量直接提升。

### B.5 Trader prompt 同时承担方向决策 + 仓位 + 止损 + 置信度

文件：`tradingagents/agents/trader/trader.py:60-98`

要求 Trader 单次给出 action / target_price / stop_loss / confidence / risk_score / 详细推理。

**问题**：单次推理同时输出 6 个相关但不独立的字段，LM 会用第一项的倾向带偏后面所有项（**自我一致性偏置**）。常见症状：confidence 永远集中在 0.7-0.85，risk_score 永远在 0.4-0.6，因为它们彼此校准而非独立估计。

**修复**：拆成两次调用或显式 chain-of-thought：

```
第一步：仅判断方向（买/卖/持有/弃权）
第二步：在第一步给定方向下，独立估计：
  - 上涨/下跌幅度区间（基于估值锚定）
  - 失败情景（哪些数据如果出现就推翻方向判断）
  - 仓位 = f(方向置信度, 波动率, 流动性)
  - 止损 = f(支撑位, 波动率)
```

### B.6 看涨/看跌 prompt 缺时间维度

bull/bear 两个 prompt 没要求"在多长时间内成立"。结果：Bull 用增长故事（3-5年），Bear 用季度业绩（1季度），二者**根本不在同一时间尺度上**，Research Manager 平均后产出无意义结论。

**修复**：在 prompt 顶部强制：

```
分析时间窗口：{horizon}（例如：未来 5 / 20 / 60 个交易日）
所有论据必须明确说明在该窗口内的因果链条。
跨窗口的论据需要折算或剔除。
```

`horizon` 应作为状态字段从入口传入。

### B.7 Report Summarizer 极可能是"拼接器"而非"分歧识别器"

`setup.py:160` 调用 `create_report_summarizer(self.quick_thinking_llm)`。如果它只是把 4 份报告拼接 / 摘要——就是把冲突信号平均掉的元凶。

**修复方向**：Summarizer prompt 必须强制：

```
你的任务不是综合，是分歧识别：
1. 列出 4 份报告中的关键事实（按报告标注来源）
2. 列出 4 份报告之间的真实冲突点（不是措辞差异）
3. 列出 4 份报告共同回避的盲区
不要做平均化的综合。让 Bull/Bear 看到真冲突。
```

### B.8 通用语言层面的小问题

- "请用中文" / "请确保所有回答都使用中文" 重复出现 8+ 次：放一次系统级 prompt 即可，每节点重复浪费 token 和注意力。
- "请以对话方式呈现，不使用特殊格式"（research_manager / debators 都有）：但下游 Trader prompt 要求结构化输出。**上游让 LLM 写散文，下游让它解析散文**——这是 SignalProcessor 出问题的常见原因。统一成结构化中间产物（dict / 标签 + 自由文本），不要让一个 LLM 解析另一个 LLM 的散文。

### B.9 辩论默认轮数 = 1，谈不上收敛

`default_config.py:17`：`max_debate_rounds=1`。Bull/Bear 各发言一次结束，没有真正交锋。`convergence_llm` 是可选，不传就只能靠计数。1 轮辩论谈不上收敛，建议生产环境 ≥ 2 并启用 convergence 检查。

---

## 四、节点 LLM 类型分配问题

LLM 类型选择对最终效果的影响**与 prompt 同等量级，部分节点甚至更大**。
当前系统只有 `quick_thinking_llm` 和 `deep_thinking_llm` 两档，分配如下（基于 `setup.py` + `trading_graph.py:599-600`）：

| 节点 | 当前 LLM | 是否合理 |
|---|---|---|
| Market Analyst | quick | OK |
| Social / News Analyst | quick | OK |
| **Fundamentals Analyst** | quick | **不合理**——需要估值推理（DCF / 相对估值），是分析师里唯一需要数学和多步推理 |
| Report Summarizer | quick | 视任务定位（拼接 OK / 分歧识别需 deep） |
| **Bull / Bear Researcher** | quick | **不合理**——上游证据质量决定 Research Manager 上限 |
| Research Manager | deep | OK |
| **Trader** | quick | **错配最大**——单次输出 6 个相关字段（方向/价格/止损/置信度/风险/推理），是链路里最复杂的多目标推理节点 |
| **Risky / Safe / Neutral** | quick | 视 Neutral 角色定位；若改"仲裁"则 Neutral 必须 deep |
| Risk Judge | deep | OK |
| **Convergence 检查** | quick | 中——立场识别需要精度高的语义对齐 |
| **Reflector**（写入 memory） | quick | **极高风险**——一次错误反思污染所有未来决策 |
| SignalProcessor（散文→结构化） | quick | 中——错则误用方向/价位 |

### D.1 Trader 用 quick 是最大错配

`setup.py:170` `trader_node = create_trader(self.quick_thinking_llm, ...)`

- 上游 4 个分析师 + Bull/Bear + Research Manager 的所有信息汇总到这里
- 输出直接进入风险辩论
- **链路上最关键决策点用最弱模型**

**建议**：Trader 必须 deep。

### D.2 辩论节点用 quick — 顺序倒了

Bull/Bear/Risky/Safe 全用 quick，Manager/Judge 用 deep。等于让实习生写报告 → 让总监判决，总监再厉害也救不了垃圾输入。
辩论的价值在于**双方用强模型刨出真冲突**。

**建议**：
- Bull/Bear 至少升 deep（或引入第三档 reasoning）
- 若按 B.4 把 Neutral 改成"仲裁角色"，**Neutral 必须 deep**
- Risky/Safe 可保持 quick，但 prompt 必须先按 A.2 改 advocacy → steelman

### D.3 Reflector 用 quick — 杠杆型风险

`trading_graph.py:599`：

```python
self.reflector = Reflector(self.quick_thinking_llm)
```

Reflector 输出写入长期 memory，被未来决策反复检索。**单次错误反思放大到所有后续决策**。

**建议**：Reflector 必须 deep。

### D.4 Fundamentals Analyst 单独成例外

`fundamentals_analyst.py` 的 prompt 让模型"计算合理价位区间、PE/PB/PEG、判断高估低估"——典型的 deep 任务。
Market/News/Social 三个分析师做指标取数 / 事件抽取 / 情绪打分，quick 足够。

**建议**：基本面分析师独立走 deep；其他三个保持 quick。

### D.5 Convergence 检查值得升级

`setup.py` 注入 `convergence_llm=self.quick_thinking_llm`。判断 Bull/Bear 是否收敛是**语义对齐 + 立场识别**任务，要求精度高于速度：

- quick 易把"措辞相似但立场不同"误判为收敛 → 提前终止辩论
- quick 易把"立场已合一但措辞不同"误判为未收敛 → 浪费 token

调用次数低（每轮辩论 1 次），升级成本可控。

### D.6 模型家族（provider）选择本身也是变量

不仅是"deep vs quick"二分，**模型家族**对系统行为影响很大：

| 模型选择 | 影响 |
|---|---|
| **GPT-4o-mini / o4-mini（默认）** | 工具调用稳，推理弱，价格便宜。复杂金融推理掉得快 |
| **Claude Sonnet / Opus** | 长上下文 + 推理强，结构化输出稳。Trader / Risk Judge / Reflector 首选 |
| **DeepSeek-R1 / o3** | 长推理链，最适合 Research Manager / Risk Judge。延迟与成本高 |
| **阿里百炼 Qwen-Max** | 中文推理 + A 股语料覆盖好，金融术语理解优于 GPT-4o-mini |
| **Gemini Pro / Flash** | tool calling 历史不稳定（代码里有 `GoogleToolCallHandler` 专门绕 bug，见 `market_analyst.py:262`、`fundamentals_analyst.py:266-288`、`news_analyst.py`）；A 股语料覆盖弱 |

代码里大量 provider 特化分支已是技术债信号。**换 provider 可能比换型号影响更大**。

### D.7 实操建议：从二档扩展为四档

把 `default_config.py` 的二分扩展为：

```python
"analyst_llm":  "...",  # 工具调用 + 模板化报告（市场/新闻/社交）
"reasoning_llm": "...", # 估值推理 + 辩论（基本面/Bull/Bear/Risky/Safe）
"decision_llm": "...",  # 关键决策（Trader/Research Manager/Risk Judge/Reflector）
"utility_llm":  "...",  # 收敛判断 / 信号解析等小任务
```

相同总成本下胜率提升空间更大。

---

## 五、优先级总结

按 ROI 排序：

| 优先级 | 改动 | 预期影响 |
|---|---|---|
| **P0** | 加回测框架 + memory 标注实际收益 | 让系统可被衡量，是其他优化的前提 |
| **P0** | 输出 schema 加 `stop_loss / risk_reward / position_size / horizon / invalidation` | 即便方向不变，仓位和止损能直接救胜率 |
| **P0** | 删掉"必须给目标价 / 不允许持有兜底"的强制语（A.1） | 立刻减少幻觉决策 |
| **P0** | Bull/Bear/Risky/Safe 改 advocacy → steelman + 概率赋权（A.2） | Manager 信号质量根本性提升 |
| **P0** | **Trader 改 deep**（D.1） | 最关键决策节点用了最弱模型 |
| **P0** | **Reflector 改 deep**（D.3） | 错误反思污染长期 memory，杠杆效应最大 |
| **P1** | 加 Regime Classifier 节点，路由到不同 prompt | 横跨牛/熊都能用 |
| **P1** | Summarizer 改"分歧识别器"，Neutral 改"仲裁角色"（B.4、B.7） | 让真冲突进决策链 |
| **P1** | 所有辩论加 horizon 字段（B.6） | 时间尺度不一致是低胜率主因之一 |
| **P1** | Trader 拆成方向→定价→仓位三步（B.5） | 解耦自一致性偏置 |
| **P1** | **Bull/Bear 改 deep**，或引入 reasoning 档（D.2） | 输入质量决定 Manager 上限 |
| **P1** | **Fundamentals Analyst 单独 deep**（D.4） | 估值推理是 deep 任务 |
| **P1** | **LLM 二档扩展为四档**（D.7） | 二档过粗，长期不可控 |
| **P2** | `online_tools / realtime_data` 默认改 true | 立即解决数据陈旧 |
| **P2** | fundamentals `max_tool_calls` 提到 3 | 解决数据不全 |
| **P2** | 删除恐吓性大写指令、把约束移到工具 schema（B.2） | 缩 prompt + 长期可维护 |
| **P2** | 市场分析师"≥800字 / 必须 4 指标"放宽为"仅报告显著信号"（B.1） | 减少凑字噪音 |
| **P2** | 中文要求统一到全局 system，去掉每节点重复（B.8） | 节省 token，注意力集中 |
| **P2** | Summarizer 把"拼接"升级为"冲突检测器"（B.7） | alpha 来源 |
| **P2** | **Convergence 检查改 deep**（D.5） | 调用次数少，升级成本可控 |
| **P2** | **评估替换 Google provider**（D.6） | 特化代码已是债务信号 |

---

## 六、建议的最小切入点

改动量最小、逻辑校正最直接的两项：

1. **A.1**：批量删除所有 prompt 中"不允许说不确定 / 必须给目标价"的强制语。
2. **B.4**：把 Neutral 风险分析师从"第三方反驳者"改为"仲裁综合者"。

两项各涉及 1-2 个文件、几十行 prompt 修改，不动状态/图结构，可立即上线 A/B 对比。
