# Workflow Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three workflow bugs: Risk Manager reading wrong state field, SignalProcessor redundant LLM call, and duplicate company name API queries.

**Architecture:** State-based caching for company names, runtime structured output detection, minimal surgical fixes.

**Tech Stack:** LangGraph, LangChain, Pydantic, TypedDict

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `tradingagents/agents/managers/risk_manager.py` | Modify line 22 + add function | Fix wrong field read + add structured output path |
| `tradingagents/agents/utils/trade_decision.py` | Create | Pydantic model for structured output |
| `tradingagents/agents/utils/agent_states.py` | Add 2 fields | `company_name` and `structured_trade_decision` |
| `tradingagents/graph/propagation.py` | Add function + modify | `_resolve_company_name()` + initial state |
| `tradingagents/agents/researchers/bull_researcher.py` | Delete ~40 lines + modify | Remove `_get_company_name()`, use state |
| `tradingagents/agents/researchers/bear_researcher.py` | Delete ~40 lines + modify | Remove `_get_company_name()`, use state |
| `tradingagents/graph/trading_graph.py` | Add method + modify `propagate()` | `_probe_structured_output()` + decision extraction |
| `tradingagents/graph/setup.py` | Modify line 169-171 | Choose structured vs fallback path |

---

### Task 1: Fix Risk Manager Wrong Field (Problem 4)

**Files:**
- Modify: `tradingagents/agents/managers/risk_manager.py:22`

- [ ] **Step 1: Fix the bug**

Change line 22 from:
```python
trader_plan = state["investment_plan"]
```
to:
```python
trader_plan = state["trader_investment_plan"]
```

- [ ] **Step 2: Verify the fix**

Run: `grep -n "trader_plan" tradingagents/agents/managers/risk_manager.py`
Expected: Line 22 shows `trader_investment_plan`

- [ ] **Step 3: Commit**

```bash
git add tradingagents/agents/managers/risk_manager.py
git commit -m "fix: Risk Manager reads trader_investment_plan instead of investment_plan

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Add Company Name to AgentState (Problem 7 - Part 1)

**Files:**
- Modify: `tradingagents/agents/utils/agent_states.py`

- [ ] **Step 1: Add company_name field**

After line 55 (`company_of_interest`), add:
```python
company_name: Annotated[str, "Human-readable company name resolved from ticker"]
```

- [ ] **Step 2: Verify**

Run: `grep -n "company_name" tradingagents/agents/utils/agent_states.py`
Expected: Shows new field definition

- [ ] **Step 3: Commit**

```bash
git add tradingagents/agents/utils/agent_states.py
git commit -m "feat: add company_name field to AgentState for caching

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Add _resolve_company_name to Propagation (Problem 7 - Part 2)

**Files:**
- Modify: `tradingagents/graph/propagation.py`

- [ ] **Step 1: Add helper function before Propagator class**

Add at line 8 (after imports, before class):
```python
def _resolve_company_name(ticker: str) -> str:
    """Resolve human-readable company name from ticker.
    
    Args:
        ticker: Stock ticker code (e.g., '600519', '00700.HK', 'AAPL')
    
    Returns:
        Company name string, or ticker itself as fallback
    """
    from tradingagents.utils.stock_utils import StockUtils
    from tradingagents.utils.logging_init import get_logger
    logger = get_logger("default")
    
    market_info = StockUtils.get_market_info(ticker)
    
    try:
        if market_info['is_china']:
            from tradingagents.dataflows.interface import get_china_stock_info_unified
            stock_info = get_china_stock_info_unified(ticker)
            if stock_info and "股票名称:" in stock_info:
                name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
                logger.info(f"✅ [Propagator] 成功获取A股名称: {ticker} -> {name}")
                return name
        elif market_info['is_hk']:
            from tradingagents.dataflows.providers.hk.improved_hk import get_hk_company_name_improved
            name = get_hk_company_name_improved(ticker)
            logger.info(f"✅ [Propagator] 成功获取港股名称: {ticker} -> {name}")
            return name
        elif market_info['is_us']:
            us_stock_names = {
                'AAPL': '苹果公司', 'TSLA': '特斯拉', 'NVDA': '英伟达',
                'MSFT': '微软', 'GOOGL': '谷歌', 'AMZN': '亚马逊',
                'META': 'Meta', 'NFLX': '奈飞'
            }
            name = us_stock_names.get(ticker.upper(), f"美股{ticker}")
            logger.info(f"✅ [Propagator] 使用美股映射: {ticker} -> {name}")
            return name
    except Exception as e:
        logger.error(f"❌ [Propagator] 获取公司名称失败: {e}")
    
    return ticker
```

- [ ] **Step 2: Modify create_initial_state to use company_name**

Change the function signature and add the lookup:
```python
def create_initial_state(
    self, ticker: str, trade_date: str
) -> Dict[str, Any]:
    """Create the initial state for the agent graph."""
    from langchain_core.messages import HumanMessage
    
    # Resolve company name once at initialization
    company_name = _resolve_company_name(ticker)
    
    # Create analysis request message
    analysis_request = f"请对股票 {company_name} 进行全面分析，交易日期为 {trade_date}。"
    
    return {
        "messages": [HumanMessage(content=analysis_request)],
        "company_of_interest": ticker,
        "company_name": company_name,
        "trade_date": str(trade_date),
        # ... rest unchanged
```

- [ ] **Step 3: Verify**

Run: `grep -n "_resolve_company_name\|company_name" tradingagents/graph/propagation.py`
Expected: Shows new function and field in initial state

- [ ] **Step 4: Commit**

```bash
git add tradingagents/graph/propagation.py
git commit -m "feat: add _resolve_company_name to cache company name in initial state

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Update Bull Researcher (Problem 7 - Part 3)

**Files:**
- Modify: `tradingagents/agents/researchers/bull_researcher.py`

- [ ] **Step 1: Delete _get_company_name function**

Delete lines 31-69 (the entire `_get_company_name` function inside `bull_node`).

- [ ] **Step 2: Replace usage with state field**

Change line 71 from:
```python
company_name = _get_company_name(ticker, market_info)
```
to:
```python
company_name = state.get("company_name", ticker)
```

Also delete line 26-28 (the StockUtils/market_info detection block) since we no longer need it for company name lookup. Keep `is_china`, `is_hk`, `is_us` detection for currency display.

- [ ] **Step 3: Simplify - keep only market detection for currency**

After deleting the `_get_company_name` block, the remaining code should be:
```python
ticker = state.get('company_of_interest', 'Unknown')
company_name = state.get("company_name", ticker)

from tradingagents.utils.stock_utils import StockUtils
market_info = StockUtils.get_market_info(ticker)
is_china = market_info['is_china']
is_hk = market_info['is_hk']
is_us = market_info['is_us']
currency = market_info['currency_name']
currency_symbol = market_info['currency_symbol']
```

- [ ] **Step 4: Verify**

Run: `grep -n "_get_company_name" tradingagents/agents/researchers/bull_researcher.py`
Expected: No matches (function deleted)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/researchers/bull_researcher.py
git commit -m "refactor: bull_researcher uses cached company_name from state

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Update Bear Researcher (Problem 7 - Part 4)

**Files:**
- Modify: `tradingagents/agents/researchers/bear_researcher.py`

- [ ] **Step 1: Delete _get_company_name function**

Delete lines 29-67 (the entire `_get_company_name` function inside `bear_node`).

- [ ] **Step 2: Replace usage with state field**

Change line 69 from:
```python
company_name = _get_company_name(ticker, market_info)
```
to:
```python
company_name = state.get("company_name", ticker)
```

- [ ] **Step 3: Simplify market detection**

Same as bull_researcher - keep only currency display logic:
```python
ticker = state.get('company_of_interest', 'Unknown')
company_name = state.get("company_name", ticker)

from tradingagents.utils.stock_utils import StockUtils
market_info = StockUtils.get_market_info(ticker)
currency = market_info['currency_name']
currency_symbol = market_info['currency_symbol']
```

- [ ] **Step 4: Verify**

Run: `grep -n "_get_company_name" tradingagents/agents/researchers/bear_researcher.py`
Expected: No matches (function deleted)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/researchers/bear_researcher.py
git commit -m "refactor: bear_researcher uses cached company_name from state

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Create TradeDecision Model (Problem 5 - Part 1)

**Files:**
- Create: `tradingagents/agents/utils/trade_decision.py`

- [ ] **Step 1: Create the Pydantic model file**

```python
from pydantic import BaseModel, Field
from typing import Optional


class TradeDecision(BaseModel):
    """Structured trade decision output model for Risk Manager."""
    
    action: str = Field(
        description="买入、持有或卖出之一"
    )
    target_price: Optional[float] = Field(
        default=None,
        description="目标价格数值，无法确定时为null"
    )
    confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="0-1之间的置信度"
    )
    risk_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="0-1之间的风险评分"
    )
    reasoning: str = Field(
        description="决策理由的中文摘要"
    )
```

- [ ] **Step 2: Verify file exists**

Run: `ls -la tradingagents/agents/utils/trade_decision.py`
Expected: File exists with correct size

- [ ] **Step 3: Commit**

```bash
git add tradingagents/agents/utils/trade_decision.py
git commit -m "feat: add TradeDecision Pydantic model for structured output

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Add structured_trade_decision to AgentState (Problem 5 - Part 2)

**Files:**
- Modify: `tradingagents/agents/utils/agent_states.py`

- [ ] **Step 1: Add structured field after final_trade_decision**

After line 85 (`final_trade_decision`), add:
```python
structured_trade_decision: Annotated[
    Optional[dict], "Structured decision dict, populated when provider supports structured output"
]
```

- [ ] **Step 2: Verify**

Run: `grep -n "structured_trade_decision" tradingagents/agents/utils/agent_states.py`
Expected: Shows new field

- [ ] **Step 3: Commit**

```bash
git add tradingagents/agents/utils/agent_states.py
git commit -m "feat: add structured_trade_decision field for provider compatibility

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: Add create_risk_manager_structured (Problem 5 - Part 3)

**Files:**
- Modify: `tradingagents/agents/managers/risk_manager.py`

- [ ] **Step 1: Add import at top**

Add after line 6:
```python
from tradingagents.agents.utils.trade_decision import TradeDecision
```

- [ ] **Step 2: Add new function after create_risk_manager**

Add after line 168:
```python
def create_risk_manager_structured(llm, memory):
    """Create Risk Manager node with structured output support.
    
    This version uses LangChain's with_structured_output() for providers
    that support it (OpenAI, Anthropic, Google). Returns a TradeDecision
    directly without needing SignalProcessor parsing.
    """
    def risk_manager_structured_node(state) -> dict:
        
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        
        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        sentiment_report = state["sentiment_report"]
        trader_plan = state["trader_investment_plan"]  # Fixed: use trader's plan
        
        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        
        # Memory lookup
        if memory is not None:
            past_memories = memory.get_memories(curr_situation, n_matches=2)
        else:
            logger.warning(f"⚠️ [Risk Manager Structured] memory为None，跳过历史记忆检索")
            past_memories = []
        
        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"
        
        # Same prompt as regular risk_manager
        prompt = f"""作为风险管理委员会主席和辩论主持人，您的目标是评估三位风险分析师——激进、中性和安全/保守——之间的辩论，并确定交易员的最佳行动方案。您的决策必须产生明确的建议：买入、卖出或持有。只有在有具体论据强烈支持时才选择持有，而不是在所有方面都似乎有效时作为后备选择。力求清晰和果断。

决策指导原则：
1. **总结关键论点**：提取每位分析师的最强观点，重点关注与背景的相关性。
2. **提供理由**：用辩论中的直接引用和反驳论点支持您的建议。
3. **完善交易员计划**：从交易员的原始计划**{trader_plan}**开始，根据分析师的见解进行调整。
4. **从过去的错误中学习**：使用**{past_memory_str}**中的经验教训来解决先前的误判，改进您现在做出的决策，确保您不会做出错误的买入/卖出/持有决定而亏损。

标的约束：
{instrument_context}

---

**分析师辩论历史：**
{history}

---

专注于可操作的见解和持续改进。建立在过去经验教训的基础上，批判性地评估所有观点，确保每个决策都能带来更好的结果。请用中文撰写所有分析内容和建议。"""

        logger.info(f"📊 [Risk Manager Structured] 开始调用LLM with structured output...")
        
        try:
            # Bind structured output
            structured_llm = llm.with_structured_output(TradeDecision)
            
            start_time = time.time()
            decision: TradeDecision = structured_llm.invoke(prompt)
            elapsed_time = time.time() - start_time
            
            logger.info(f"⏱️ [Risk Manager Structured] LLM调用耗时: {elapsed_time:.2f}秒")
            logger.info(f"✅ [Risk Manager Structured] 结构化输出成功: action={decision.action}, confidence={decision.confidence}")
            
            # Convert to dict for state
            decision_dict = decision.model_dump()
            
            # Also create text version for final_trade_decision (backward compat)
            response_content = f"""**建议：{decision.action}**

**目标价格：** {decision.target_price if decision.target_price else '未确定'}

**置信度：** {decision.confidence:.2f}

**风险评分：** {decision.risk_score:.2f}

**理由：** {decision.reasoning}"""
            
        except Exception as e:
            logger.error(f"❌ [Risk Manager Structured] 结构化输出失败: {e}")
            # Fallback to default decision
            decision_dict = {
                "action": "持有",
                "target_price": None,
                "confidence": 0.7,
                "risk_score": 0.5,
                "reasoning": f"结构化输出失败，使用默认决策: {str(e)}"
            }
            response_content = f"""**默认建议：持有**

由于技术原因无法生成详细分析，建议对{company_name}采取持有策略。
注意：此为系统默认建议。"""
        
        new_risk_debate_state = {
            "judge_decision": response_content,
            "history": risk_debate_state["history"],
            "risky_history": risk_debate_state["risky_history"],
            "safe_history": risk_debate_state["safe_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_risky_response": risk_debate_state["current_risky_response"],
            "current_safe_response": risk_debate_state["current_safe_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }
        
        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": response_content,
            "structured_trade_decision": decision_dict,
        }
    
    return risk_manager_structured_node
```

- [ ] **Step 3: Verify**

Run: `grep -n "create_risk_manager_structured" tradingagents/agents/managers/risk_manager.py`
Expected: Shows new function definition

- [ ] **Step 4: Commit**

```bash
git add tradingagents/agents/managers/risk_manager.py
git commit -m "feat: add create_risk_manager_structured for structured output support

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: Add provider detection to TradingGraph (Problem 5 - Part 4)

**Files:**
- Modify: `tradingagents/graph/trading_graph.py`

- [ ] **Step 1: Add import for TradeDecision**

Add in imports section:
```python
from tradingagents.agents.utils.trade_decision import TradeDecision
```

- [ ] **Step 2: Add _probe_structured_output method**

Add after __init__ method (around line 600):
```python
def _probe_structured_output(self, llm) -> bool:
    """Check if LLM provider supports structured output.
    
    This is a no-network-call check - with_structured_output() only
    constructs a binding object, doesn't invoke the LLM.
    
    Returns:
        True if provider supports structured output, False otherwise
    """
    try:
        llm.with_structured_output(TradeDecision)
        logger.info(f"✅ [TradingGraph] Provider supports structured output")
        return True
    except (NotImplementedError, AttributeError) as e:
        logger.info(f"⚠️ [TradingGraph] Provider does not support structured output: {e}")
        return False
```

- [ ] **Step 3: Call probe in __init__ and pass to GraphSetup**

In __init__, after LLM creation (around line 576), add:
```python
# Detect structured output capability
self._supports_structured_output = self._probe_structured_output(self.deep_thinking_llm)
```

Then modify GraphSetup instantiation to pass the flag:
```python
self.graph_setup = GraphSetup(
    self.quick_thinking_llm,
    self.deep_thinking_llm,
    self.toolkit,
    self.tool_nodes,
    self.bull_memory,
    self.bear_memory,
    self.trader_memory,
    self.invest_judge_memory,
    self.risk_manager_memory,
    self.conditional_logic,
    self.config,
    getattr(self, 'react_llm', None),
    supports_structured_output=self._supports_structured_output,
)
```

- [ ] **Step 4: Modify propagate() to use structured output**

Around line 853, change:
```python
# Add progress callback for signal processing (fixes existing bug)
if progress_callback:
    progress_callback("📡 信号处理")

# Use structured decision if available, otherwise parse
if final_state.get("structured_trade_decision"):
    decision = final_state["structured_trade_decision"]
    logger.info(f"✅ [Propagate] 使用结构化决策输出")
else:
    decision = self.process_signal(final_state["final_trade_decision"], company_name)
    logger.info(f"⚠️ [Propagate] 使用SignalProcessor解析")

decision['model_info'] = model_info
```

- [ ] **Step 5: Verify**

Run: `grep -n "_probe_structured_output\|supports_structured_output\|structured_trade_decision" tradingagents/graph/trading_graph.py`
Expected: Shows all three additions

- [ ] **Step 6: Commit**

```bash
git add tradingagents/graph/trading_graph.py
git commit -m "feat: add structured output detection and dual-path decision extraction

- Add _probe_structured_output() for provider capability detection
- Pass supports_structured_output flag to GraphSetup
- propagate() uses structured_trade_decision when available
- Add missing progress_callback for signal processing step

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 10: Update GraphSetup for structured output (Problem 5 - Part 5)

**Files:**
- Modify: `tradingagents/graph/setup.py`

- [ ] **Step 1: Add import**

Add in imports (after line 17):
```python
from tradingagents.agents.managers.risk_manager import create_risk_manager_structured
```

- [ ] **Step 2: Add parameter to __init__**

Add `supports_structured_output` parameter after `react_llm`:
```python
def __init__(
    self,
    quick_thinking_llm: ChatOpenAI,
    deep_thinking_llm: ChatOpenAI,
    toolkit: Toolkit,
    tool_nodes: Dict[str, ToolNode],
    bull_memory,
    bear_memory,
    trader_memory,
    invest_judge_memory,
    risk_manager_memory,
    conditional_logic: ConditionalLogic,
    config: Dict[str, Any] = None,
    react_llm = None,
    supports_structured_output: bool = False,
):
    # ... existing init code ...
    self.supports_structured_output = supports_structured_output
```

- [ ] **Step 3: Modify risk_manager_node creation**

Change lines 169-171 from:
```python
risk_manager_node = create_risk_manager(
    self.deep_thinking_llm, self.risk_manager_memory
)
```
to:
```python
if self.supports_structured_output:
    logger.info(f"🔧 [GraphSetup] Using structured Risk Manager")
    risk_manager_node = create_risk_manager_structured(
        self.deep_thinking_llm, self.risk_manager_memory
    )
else:
    logger.info(f"🔧 [GraphSetup] Using standard Risk Manager")
    risk_manager_node = create_risk_manager(
        self.deep_thinking_llm, self.risk_manager_memory
    )
```

- [ ] **Step 4: Verify**

Run: `grep -n "supports_structured_output\|create_risk_manager_structured" tradingagents/graph/setup.py`
Expected: Shows parameter and conditional logic

- [ ] **Step 5: Commit**

```bash
git add tradingagents/graph/setup.py
git commit -m "feat: GraphSetup chooses structured vs standard Risk Manager based on provider

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11: Integration Test

**Files:**
- Run integration test

- [ ] **Step 1: Run a simple workflow test**

Run the workflow with a known ticker (e.g., 600519) and verify:
1. Company name appears only once in logs (from Propagator)
2. Risk Manager reads trader_investment_plan (check prompt in logs)
3. For OpenAI/Anthropic: structured_trade_decision appears in state

- [ ] **Step 2: Check for regressions**

Verify all existing tests still pass (if test suite exists).

---

## Summary

| Task | Problem | Risk |
|------|---------|------|
| 1 | Problem 4 (wrong field) | Very Low - 1 line |
| 2-5 | Problem 7 (company name cache) | Low - state schema + 4 files |
| 6-10 | Problem 5 (structured output) | Medium - new path, dual-mode |

Implementation order: 1 → 2-5 → 6-10 (as specified in design doc).