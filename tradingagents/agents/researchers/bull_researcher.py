from langchain_core.messages import AIMessage
import time
import json

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")


def create_bull_researcher(llm, memory):
    def bull_node(state) -> dict:
        logger.debug(f"🐂 [DEBUG] ===== 看涨研究员节点开始 =====")

        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

        current_response = investment_debate_state.get("current_response", "")
        combined_report_summary = state.get("combined_report_summary", "")
        horizon = state.get("horizon", "未来 3 个交易日")

        # 使用统一的股票类型检测（仅用于货币显示）
        ticker = state.get('company_of_interest', 'Unknown')
        company_name = state.get("company_name", ticker)
        from tradingagents.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(ticker)
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        is_us = market_info['is_us']

        currency = market_info['currency_name']
        currency_symbol = market_info['currency_symbol']

        logger.debug(f"🐂 [DEBUG] 接收到的摘要:")
        logger.debug(f"🐂 [DEBUG] - 综合摘要长度: {len(combined_report_summary)}")
        logger.debug(f"🐂 [DEBUG] - 股票代码: {ticker}, 公司名称: {company_name}, 类型: {market_info['market_name']}, 货币: {currency}")
        logger.debug(f"🐂 [DEBUG] - 市场详情: 中国A股={is_china}, 港股={is_hk}, 美股={is_us}")

        curr_situation = combined_report_summary

        # 安全检查：确保memory不为None
        if memory is not None:
            past_memories = memory.get_memories(curr_situation, n_matches=2)
        else:
            logger.warning(f"⚠️ [DEBUG] memory为None，跳过历史记忆检索")
            past_memories = []

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        prompt = f"""你是一位看涨方分析师，负责为 {company_name}（{ticker}）的投资价值进行诚实评估。

⚠️ 你的任务不是赢得辩论，而是提供客观的看涨证据评估。
⚠️ 在你的分析中，请始终使用公司名称"{company_name}"而不是股票代码"{ticker}"来称呼这家公司。
⚠️ 所有价格和估值请使用 {currency}（{currency_symbol}）作为单位。

分析时间窗口：{horizon}

请严格按照以下三部分结构输出：

## 一、看涨论据
列出 3-5 条证据，每条必须标注：
- **证据内容**：具体事实或数据
- **证据强度**（强/中/弱）：基于什么数据支撑
- **最强反驳**：如果从看跌角度看，这个论据最有力的反驳是什么

## 二、主观概率
你认为该标的在未来 3 个交易日内上涨超过 10% 的概率是多少？（0-1，并说明理由）

## 三、看错信号
如果什么数据或事件出现，就承认看涨判断是错的？列出 2-3 个具体条件。

可用资源：
综合分析摘要：{combined_report_summary}
辩论对话历史：{history}
最后的看跌论点：{current_response}
类似情况的反思：{past_memory_str}

请使用中文回答。
"""

        response = llm.invoke(prompt)

        argument = f"Bull Analyst: {response.content}"

        new_count = investment_debate_state["count"] + 1
        logger.info(f"🐂 [多头研究员] 发言完成，计数: {investment_debate_state['count']} -> {new_count}")

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": new_count,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
