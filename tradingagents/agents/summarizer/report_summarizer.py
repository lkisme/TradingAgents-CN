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

        prompt = f"""你的任务是客观提取所有核心决策信息并明确标注分歧，不做主观综合、不平均冲突观点。请基于以下四份分析师报告输出结构化结果，上限3000字。

输出必须包含四部分，所有内容都基于原始报告客观提取，不添加主观判断：

一、核心决策要素汇总（按维度分类，标注来源）
  把所有报告中的关键决策信息按维度分类列出，每条标注来自哪份报告（市场/情绪/新闻/基本面）。
  必须包含以下维度，没有的信息标注「无」：
  - 📈 价格维度：所有价格相关信息：当前价、支撑位、阻力位、估值区间、各分析师给出的目标价
  - 📊 立场维度：各分析师明确的多空立场：看涨/看跌/中性
  - ⏰ 催化剂维度：所有提到的重要时间节点/事件：财报、政策、行业事件、解禁、限售等
  - 💰 估值维度：关键估值参数：PE、PB、PEG、业绩增速、行业平均估值等
  - ⚠️ 风险维度：所有明确提到的风险因素、风险等级、风险评分、风险强度、下行空间、数据质量风险

二、报告间真实冲突点
  列出报告之间的实质性冲突（不是措辞差异），例如：
  - 基本面看空 vs 新闻面看多
  - 技术面看涨 vs 情绪面看跌
  每个冲突标注：冲突双方各自的依据。
  如果没有实质性冲突，说明各报告方向一致。

三、共同盲区
  列出 4 份报告共同回避或未覆盖的关键问题（如缺少某类数据、未考虑某风险因素）。
  如果没有明显盲区，说明覆盖较完整。

四、核心观点索引
  提取每份报告的核心结论片段（100字以内/每份），不做修改，直接引用原始表述。

五、数据质量检查
  检查哪些报告明确使用了真实工具数据，哪些报告存在数据缺失、失败、过期或兜底分析。
  每份报告都必须给出一个数据状态：完整/部分/失败/未说明，并标注依据。

六、可供后续决策使用的事实清单
  只列事实，不列推断。每条事实必须标注来源报告，优先列出价格、估值、新闻事件、情绪指标和明确风险。
  如果事实来自失败、过期或兜底分析，必须标注「低可信」。

七、风险评分输入摘要
  为后续风险经理计算risk_score提供结构化输入，必须包含：
  - 明确风险因素清单：每条标注来源和影响方向
  - 风险强度：低/中等/高/极高；如原报告有数字评分，必须保留原数字
  - 数据质量风险：完整/部分/失败/未说明，以及它对风险评分的影响
  - 可量化下行风险：支撑位、止损位、潜在跌幅或最大亏损；没有则标注「无」
  - 风险评分建议区间：基于原始报告事实给出0-1区间（如0.55-0.70），不要只写“中等”

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

请用中文撰写，控制在3000字以内。"""

        start_time = time.time()
        response = llm.invoke(prompt)
        elapsed = time.time() - start_time

        summary = response.content if hasattr(response, 'content') else str(response)

        logger.info(f"✅ [Report Summarizer] 摘要生成完成，耗时: {elapsed:.2f}秒")
        logger.info(f"  - 摘要长度: {len(summary):,} 字符")

        return {"combined_report_summary": summary}

    return report_summarizer_node
