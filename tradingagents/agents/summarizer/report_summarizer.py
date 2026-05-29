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

        prompt = f"""你的任务不是综合，是分歧识别和信息保留。请基于以下四份分析师报告输出结构化的分歧分析，上限2500字。

输出必须包含三部分：

一、关键事实（按报告标注来源）
  列出 4 份报告中的核心数据和事实，每条标注来自哪份报告（市场/情绪/新闻/基本面）。
  保留关键财务数据（价格、估值、财务指标）。

二、报告间真实冲突点
  列出报告之间的实质性冲突（不是措辞差异），例如：
  - 基本面看空 vs 新闻面看多
  - 技术面看涨 vs 情绪面看跌
  每个冲突标注：冲突双方各自的依据。
  如果没有实质性冲突，说明各报告方向一致。

三、共同盲区
  列出 4 份报告共同回避或未覆盖的关键问题（如缺少某类数据、未考虑某风险因素）。
  如果没有明显盲区，说明覆盖较完整。

不做投资建议，不做平均化综合。

---

市场分析报告：
{market_report}

社交媒体情绪报告：
{sentiment_report}

新闻分析报告：
{news_report}

基本面分析报告：
{fundamentals_report}

请用中文撰写，控制在2500字以内。"""

        start_time = time.time()
        response = llm.invoke(prompt)
        elapsed = time.time() - start_time

        summary = response.content if hasattr(response, 'content') else str(response)

        logger.info(f"✅ [Report Summarizer] 摘要生成完成，耗时: {elapsed:.2f}秒")
        logger.info(f"  - 摘要长度: {len(summary):,} 字符")

        return {"combined_report_summary": summary}

    return report_summarizer_node