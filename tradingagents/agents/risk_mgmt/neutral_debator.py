import time
import json

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")


def create_neutral_debator(llm):
    def neutral_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")

        current_risky_response = risk_debate_state.get("current_risky_response", "")
        current_safe_response = risk_debate_state.get("current_safe_response", "")

        combined_report_summary = state.get("combined_report_summary", "")
        horizon = state.get("horizon", "未来 3 个交易日")

        trader_decision = state["trader_investment_plan"]

        # 📊 记录所有输入数据的长度，用于性能分析
        logger.info(f"📊 [Neutral Analyst] 输入数据长度统计:")
        logger.info(f"  - combined_report_summary: {len(combined_report_summary):,} 字符 (~{len(combined_report_summary)//4:,} tokens)")
        logger.info(f"  - trader_decision: {len(trader_decision):,} 字符 (~{len(trader_decision)//4:,} tokens)")
        logger.info(f"  - history: {len(history):,} 字符 (~{len(history)//4:,} tokens)")
        logger.info(f"  - current_risky_response: {len(current_risky_response):,} 字符 (~{len(current_risky_response)//4:,} tokens)")
        logger.info(f"  - current_safe_response: {len(current_safe_response):,} 字符 (~{len(current_safe_response)//4:,} tokens)")

        # 计算总prompt长度
        total_prompt_length = (len(combined_report_summary) +
                              len(trader_decision) + len(history) +
                              len(current_risky_response) + len(current_safe_response))
        logger.info(f"  - 🚨 总Prompt长度: {total_prompt_length:,} 字符 (~{total_prompt_length//4:,} tokens)")

        prompt = f"""你是风险综合分析师。前置：激进和安全分析师已发言。你的任务不是提出第三方观点，而是仲裁和综合。

分析时间窗口：{horizon}

交易员的决策：
{trader_decision}

综合分析摘要：
{combined_report_summary}

以下是当前对话历史：
{history}

以下是激进分析师的最后回应：
{current_risky_response}

以下是安全分析师的最后回应：
{current_safe_response}

如果某方尚未回应，请基于已有发言进行综合，不要虚构。

输出必须包含四部分：
1. **双方一致的事实**：列出激进方和安全方都认同的客观事实（不仅是观点）
2. **真正的分歧点**：列出双方实质性分歧（不是措辞差异），每个分歧标注：
   - 分歧的核心是什么
   - 各方论据强度（强/中/弱）
3. **条件判断**：对每个分歧点，给出"在何种市场条件下倾向哪一方"
4. **风险区间建议**：基于综合判断，给出仓位区间建议和止损区间建议（不是 buy/sell 决策）

如果双方没有实质性分歧，直接说明共识点即可。请用中文输出。"""

        logger.info(f"⏱️ [Neutral Analyst] 开始调用LLM...")
        llm_start_time = time.time()

        response = llm.invoke(prompt)

        llm_elapsed = time.time() - llm_start_time
        logger.info(f"⏱️ [Neutral Analyst] LLM调用完成，耗时: {llm_elapsed:.2f}秒")
        logger.info(f"📝 [Neutral Analyst] 响应长度: {len(response.content):,} 字符")

        argument = f"Neutral Analyst: {response.content}"

        new_count = risk_debate_state["count"] + 1
        logger.info(f"⚖️ [中性风险分析师] 发言完成，计数: {risk_debate_state['count']} -> {new_count}")

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "risky_history": risk_debate_state.get("risky_history", ""),
            "safe_history": risk_debate_state.get("safe_history", ""),
            "neutral_history": neutral_history + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_risky_response": risk_debate_state.get(
                "current_risky_response", ""
            ),
            "current_safe_response": risk_debate_state.get("current_safe_response", ""),
            "current_neutral_response": argument,
            "count": new_count,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return neutral_node
