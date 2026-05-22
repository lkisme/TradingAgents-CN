import time

from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")


def create_report_summarizer(llm):
    """Create a node that summarizes all analyst reports into a combined summary.

    Args:
        llm: The LLM to use for summarization (typically quick_thinking_llm)

    Returns:
        A node function that generates combined_report_summary
    """
    def report_summarizer_node(state) -> dict:
        market_report = state.get("market_report", "")
        sentiment_report = state.get("sentiment_report", "")
        news_report = state.get("news_report", "")
        fundamentals_report = state.get("fundamentals_report", "")

        # 检查是否有报告内容
        if not any([market_report, sentiment_report, news_report, fundamentals_report]):
            logger.warning("⚠️ [Report Summarizer] 没有可用的分析报告")
            return {"combined_report_summary": "暂无分析报告数据。"}

        logger.info("📝 [Report Summarizer] 开始生成综合摘要...")
        logger.info(f"  - market_report: {len(market_report):,} 字符")
        logger.info(f"  - sentiment_report: {len(sentiment_report):,} 字符")
        logger.info(f"  - news_report: {len(news_report):,} 字符")
        logger.info(f"  - fundamentals_report: {len(fundamentals_report):,} 字符")

        prompt = f"""请将以下四份分析师报告整合成一份综合摘要，上限2000字。

要求：
1. 保留关键财务数据（价格、估值、财务指标）
2. 保留核心风险因素和机会点
3. 保留市场情绪倾向
4. 不做投资建议，只做信息整合
5. 使用简洁清晰的语言

市场分析报告：
{market_report}

社交媒体情绪报告：
{sentiment_report}

新闻分析报告：
{news_report}

基本面分析报告：
{fundamentals_report}

请用中文撰写综合摘要，控制在2000字以内。"""

        start_time = time.time()
        response = llm.invoke(prompt)
        elapsed = time.time() - start_time

        summary = response.content if hasattr(response, 'content') else str(response)

        logger.info(f"✅ [Report Summarizer] 摘要生成完成，耗时: {elapsed:.2f}秒")
        logger.info(f"  - 摘要长度: {len(summary):,} 字符")

        return {"combined_report_summary": summary}

    return report_summarizer_node