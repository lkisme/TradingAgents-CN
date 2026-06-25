import time
import json

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")


def create_risky_debator(llm):
    def risky_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        risky_history = risk_debate_state.get("risky_history", "")

        current_safe_response = risk_debate_state.get("current_safe_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        combined_report_summary = state.get("combined_report_summary", "")
        horizon = state.get("horizon", "未来 3 个交易日")

        trader_decision = state["trader_investment_plan"]

        # 📊 记录输入数据长度
        logger.info(f"📊 [Risky Analyst] 输入数据长度统计:")
        logger.info(f"  - combined_report_summary: {len(combined_report_summary):,} 字符")
        logger.info(f"  - trader_decision: {len(trader_decision):,} 字符")
        logger.info(f"  - history: {len(history):,} 字符")
        total_length = (len(combined_report_summary) +
                       len(trader_decision) + len(history) +
                       len(current_safe_response) + len(current_neutral_response))
        logger.info(f"  - 总Prompt长度: {total_length:,} 字符 (~{total_length//4:,} tokens)")

        prompt = f"""你是一位激进风险分析师，负责从高风险高回报视角评估交易员决策。

分析时间窗口：{horizon}

⚠️ 你的任务不是倡导冒险，而是客观评估激进策略的证据和风险。

请严格按照以下结构输出：

## 一、激进策略论据
列出支持高风险策略的证据，每条标注：
- **证据内容**和**证据强度**（强/中/弱）
- **最强反驳**：保守方会如何反驳

## 二、预期回报与风险
- 激进策略的预期回报幅度
- 最大可能亏损幅度
- 成功概率估计（0-1）
- 下行风险评分（0-1）：0.0-0.3低，0.3-0.6中，0.6-0.8高，0.8-1.0极高
- 波动风险评分（0-1）
- 数据质量风险评分（0-1）
- 激进策略综合风险评分（0-1）
- 风险评分依据：说明上述评分来自哪些证据，不允许只写“中等”

## 三、失效条件
什么情况下激进策略会失败？列出具体信号。

交易员决策：{trader_decision}
综合分析摘要：{combined_report_summary}
对话历史：{history}
保守方最后论点：{current_safe_response}
中性方最后论点：{current_neutral_response}

请使用中文回答。"""

        logger.info(f"⏱️ [Risky Analyst] 开始调用LLM...")
        import time
        llm_start_time = time.time()

        response = llm.invoke(prompt)

        llm_elapsed = time.time() - llm_start_time
        logger.info(f"⏱️ [Risky Analyst] LLM调用完成，耗时: {llm_elapsed:.2f}秒")

        argument = f"Risky Analyst: {response.content}"

        new_count = risk_debate_state["count"] + 1
        logger.info(f"🔥 [激进风险分析师] 发言完成，计数: {risk_debate_state['count']} -> {new_count}")

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "risky_history": risky_history + "\n" + argument,
            "safe_history": risk_debate_state.get("safe_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Risky",
            "current_risky_response": argument,
            "current_safe_response": risk_debate_state.get("current_safe_response", ""),
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": new_count,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return risky_node
