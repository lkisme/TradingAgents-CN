from langchain_core.messages import AIMessage
import time
import json

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")


def create_safe_debator(llm):
    def safe_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        safe_history = risk_debate_state.get("safe_history", "")

        current_risky_response = risk_debate_state.get("current_risky_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        combined_report_summary = state.get("combined_report_summary", "")
        horizon = state.get("horizon", "未来 3 个交易日")

        trader_decision = state["trader_investment_plan"]

        # 📊 记录输入数据长度
        logger.info(f"📊 [Safe Analyst] 输入数据长度统计:")
        logger.info(f"  - combined_report_summary: {len(combined_report_summary):,} 字符")
        logger.info(f"  - trader_decision: {len(trader_decision):,} 字符")
        logger.info(f"  - history: {len(history):,} 字符")
        total_length = (len(combined_report_summary) +
                       len(trader_decision) + len(history) +
                       len(current_risky_response) + len(current_neutral_response))
        logger.info(f"  - 总Prompt长度: {total_length:,} 字符 (~{total_length//4:,} tokens)")

        prompt = f"""你是一位保守风险分析师，负责从风险控制视角评估交易员决策。

分析时间窗口：{horizon}

⚠️ 你的任务不是反对一切风险，而是客观评估保守策略的证据和代价。

请严格按照以下结构输出：

## 一、保守策略论据
列出支持低风险策略的证据，每条标注：
- **证据内容**和**证据强度**（强/中/弱）
- **最强反驳**：激进方会如何反驳

## 二、风险评估
- 当前策略的最大风险点
- 最坏情况下的损失估计
- 保守策略的机会成本（错失的收益）

## 三、失效条件
什么情况下保守策略会错失机会？列出具体信号。

交易员决策：{trader_decision}
综合分析摘要：{combined_report_summary}
对话历史：{history}
激进方最后论点：{current_risky_response}
中性方最后论点：{current_neutral_response}

请使用中文回答。"""

        logger.info(f"⏱️ [Safe Analyst] 开始调用LLM...")
        llm_start_time = time.time()

        response = llm.invoke(prompt)

        llm_elapsed = time.time() - llm_start_time
        logger.info(f"⏱️ [Safe Analyst] LLM调用完成，耗时: {llm_elapsed:.2f}秒")

        argument = f"Safe Analyst: {response.content}"

        new_count = risk_debate_state["count"] + 1
        logger.info(f"🛡️ [保守风险分析师] 发言完成，计数: {risk_debate_state['count']} -> {new_count}")

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "risky_history": risk_debate_state.get("risky_history", ""),
            "safe_history": safe_history + "\n" + argument,
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Safe",
            "current_risky_response": risk_debate_state.get(
                "current_risky_response", ""
            ),
            "current_safe_response": argument,
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": new_count,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return safe_node
