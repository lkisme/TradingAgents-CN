from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json

# 导入统一日志系统和分析模块日志装饰器
from tradingagents.utils.logging_init import get_logger
from tradingagents.utils.tool_logging import log_analyst_module
logger = get_logger("analysts.social_media")

# 导入Google工具调用处理器
from tradingagents.agents.utils.google_tool_handler import GoogleToolCallHandler
from tradingagents.agents.utils.instrument_utils import build_instrument_context


def _get_company_name_for_social_media(ticker: str, market_info: dict) -> str:
    """
    为社交媒体分析师获取公司名称

    Args:
        ticker: 股票代码
        market_info: 市场信息字典

    Returns:
        str: 公司名称
    """
    try:
        if market_info['is_china']:
            # 中国A股：使用统一接口获取股票信息
            from tradingagents.dataflows.interface import get_china_stock_info_unified
            stock_info = get_china_stock_info_unified(ticker)

            logger.debug(f"📊 [社交媒体分析师] 获取股票信息返回: {stock_info[:200] if stock_info else 'None'}...")

            # 解析股票名称
            if stock_info and "股票名称:" in stock_info:
                company_name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
                logger.info(f"✅ [社交媒体分析师] 成功获取中国股票名称: {ticker} -> {company_name}")
                return company_name
            else:
                # 降级方案：尝试直接从数据源管理器获取
                logger.warning(f"⚠️ [社交媒体分析师] 无法从统一接口解析股票名称: {ticker}，尝试降级方案")
                try:
                    from tradingagents.dataflows.data_source_manager import get_china_stock_info_unified as get_info_dict
                    info_dict = get_info_dict(ticker)
                    if info_dict and info_dict.get('name'):
                        company_name = info_dict['name']
                        logger.info(f"✅ [社交媒体分析师] 降级方案成功获取股票名称: {ticker} -> {company_name}")
                        return company_name
                except Exception as e:
                    logger.error(f"❌ [社交媒体分析师] 降级方案也失败: {e}")

                logger.error(f"❌ [社交媒体分析师] 所有方案都无法获取股票名称: {ticker}")
                return f"股票代码{ticker}"

        elif market_info['is_hk']:
            # 港股：使用改进的港股工具
            try:
                from tradingagents.dataflows.providers.hk.improved_hk import get_hk_company_name_improved
                company_name = get_hk_company_name_improved(ticker)
                logger.debug(f"📊 [社交媒体分析师] 使用改进港股工具获取名称: {ticker} -> {company_name}")
                return company_name
            except Exception as e:
                logger.debug(f"📊 [社交媒体分析师] 改进港股工具获取名称失败: {e}")
                # 降级方案：生成友好的默认名称
                clean_ticker = ticker.replace('.HK', '').replace('.hk', '')
                return f"港股{clean_ticker}"

        elif market_info['is_us']:
            # 美股：使用简单映射或返回代码
            us_stock_names = {
                'AAPL': '苹果公司',
                'TSLA': '特斯拉',
                'NVDA': '英伟达',
                'MSFT': '微软',
                'GOOGL': '谷歌',
                'AMZN': '亚马逊',
                'META': 'Meta',
                'NFLX': '奈飞'
            }

            company_name = us_stock_names.get(ticker.upper(), f"美股{ticker}")
            logger.debug(f"📊 [社交媒体分析师] 美股名称映射: {ticker} -> {company_name}")
            return company_name

        else:
            return f"股票{ticker}"

    except Exception as e:
        logger.error(f"❌ [社交媒体分析师] 获取公司名称失败: {e}")
        return f"股票{ticker}"


def create_social_media_analyst(llm, toolkit):
    @log_analyst_module("social_media")
    def social_media_analyst_node(state):
        # 🔧 工具调用计数器 - 防止无限循环
        tool_call_count = state.get("sentiment_tool_call_count", 0)
        max_tool_calls = 3  # 最大工具调用次数
        logger.info(f"🔧 [死循环修复] 当前工具调用次数: {tool_call_count}/{max_tool_calls}")

        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        # 获取股票市场信息
        from tradingagents.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(ticker)

        # 获取公司名称
        company_name = _get_company_name_for_social_media(ticker, market_info)
        instrument_context = build_instrument_context(ticker)
        logger.info(f"[社交媒体分析师] 公司名称: {company_name}")

        # 统一使用 get_stock_sentiment_unified 工具
        # 该工具内部会自动识别股票类型并调用相应的情绪数据源
        logger.info(f"[社交媒体分析师] 使用统一情绪分析工具，自动识别股票类型")
        tools = [toolkit.get_stock_sentiment_unified]
        output_contract = (
            "## 结构化结论\n"
            "- 数据状态：完整/部分/失败\n"
            "- 方向：看涨/中性/看跌\n"
            "- 置信度：0-1\n"
            "- 当前价格：如果情绪数据未提供则写「无」\n"
            "- 目标价/区间：如果没有当前价，不得给出具体目标价，只能说明情绪影响方向\n"
            "- 核心证据：最多5条\n"
            "- 主要风险：最多5条\n"
            "- 缺失数据：无/列出缺失项\n"
            "\n"
            "目标价一致性规则：如果给出买入倾向，目标价必须高于当前价并说明情绪或资金依据；"
            "如果给出卖出倾向，目标价必须低于当前价或给出止损依据；"
            "如果没有当前价，不得给出确定性目标价。\n"
        )

        system_message = (
            f"""您是一位专业的中国市场社交媒体和投资情绪分析师，负责分析中国投资者对特定股票的讨论和情绪变化。

您现在能访问真实的东方财富股吧情绪指数数据和财经新闻，这是核心分析依据。

## 情绪指数数据解读

您将获取以下真实情绪指数数据，请按以下系数解读：

### 情绪指数系数说明

| 指标 | 数值范围 | 高值含义（阈值） | 低值含义（阈值） |
|------|----------|------------------|------------------|
| **参与意愿** | 0-100 | 50+: 散户讨论热烈，市场活跃度高 | 30以下: 活跃度低，关注度不足 |
| **关注度** | 60-100 | 80+: 热点股，市场高度关注 | 70以下: 关注度下降，热度减弱 |
| **综合评价** | 50-80 | 70+: 投资者情绪偏乐观 | 50-60: 偏悲观，需关注风险 |
| **机构参与度** | 20-60 | 40+: 机构投资者活跃，专业资金参与 | 30以下: 散户主导，机构关注度低 |

### 特殊组合信号解读

- **高关注(80+) + 低参与意愿(<30)** = 观望态度（市场关注但不愿参与，等待更明确信号）
- **高参与意愿(50+) + 低机构参与(<30)** = 散户主导行情，需关注持续性风险
- **机构活跃(40+) + 综合评价乐观(70+)** = 专业投资者看好，可能有基本面支撑

## 分析要点

1. **情绪趋势判断**：分析情绪指数变化趋势（如参与意愿变化值）
2. **情绪背离识别**：散户情绪与机构情绪的背离情况
3. **极端情绪预警**：情绪极端点的反转可能性
4. **财经新闻解读**：结合新闻内容判断情绪驱动因素
5. **影响周期评估**：情绪对短期(1-5天)股价的潜在影响

## 输出要求

📊 情绪分析报告必须包含：
- 情绪综合评分（1-10分）
- 各情绪指数的具体解读（基于系数表）
- 情绪对短期价格波动的影响预测（幅度预估）
- 交易时机建议（基于情绪分析）

⚠️ 注意：
- 必须使用真实数据进行分析，不允许回复"无法评估"或"需要更多数据"
- 财经新闻应作为情绪解读的辅助依据
- 请用中文撰写详细分析报告

{output_contract}"""
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "您是一位有用的AI助手，与其他助手协作。"
                    " 使用提供的工具来推进回答问题。"
                    " 如果您无法完全回答，没关系；具有不同工具的其他助手"
                    " 将从您停下的地方继续帮助。执行您能做的以取得进展。"
                    " 如果您或任何其他助手有最终交易提案：**买入/持有/卖出**或可交付成果，"
                    " 请在您的回应前加上最终交易提案：**买入/持有/卖出**，以便团队知道停止。"
                    " 您可以访问以下工具：{tool_names}。\n标的约束：{instrument_context}\n{system_message}"
                    "供您参考，当前日期是{current_date}。我们要分析的当前公司是{ticker}。请用中文撰写所有分析内容。",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        # 安全地获取工具名称，处理函数和工具对象
        tool_names = []
        for tool in tools:
            if hasattr(tool, 'name'):
                tool_names.append(tool.name)
            elif hasattr(tool, '__name__'):
                tool_names.append(tool.__name__)
            else:
                tool_names.append(str(tool))

        prompt = prompt.partial(tool_names=", ".join(tool_names))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        # 修复：传递字典而不是直接传递消息列表，以便 ChatPromptTemplate 能正确处理所有变量
        result = chain.invoke({"messages": state["messages"]})

        # 使用统一的Google工具调用处理器
        if GoogleToolCallHandler.is_google_model(llm):
            logger.info(f"📊 [社交媒体分析师] 检测到Google模型，使用统一工具调用处理器")
            
            # 创建分析提示词
            analysis_prompt_template = GoogleToolCallHandler.create_analysis_prompt(
                ticker=ticker,
                company_name=company_name,
                analyst_type="社交媒体情绪分析",
                specific_requirements="重点关注投资者情绪、社交媒体讨论热度、舆论影响等。"
            )
            
            # 处理Google模型工具调用
            report, messages = GoogleToolCallHandler.handle_google_tool_calls(
                result=result,
                llm=llm,
                tools=tools,
                state=state,
                analysis_prompt_template=analysis_prompt_template,
                analyst_name="社交媒体分析师"
            )
        else:
            # 非Google模型的处理逻辑（参考 Market Analyst）
            logger.info(f"📊 [社交媒体分析师] 非Google模型 ({llm.__class__.__name__})，使用标准处理逻辑")
            logger.info(f"📊 [社交媒体分析师] - 是否有tool_calls: {hasattr(result, 'tool_calls')}")
            if hasattr(result, 'tool_calls'):
                logger.info(f"📊 [社交媒体分析师] - tool_calls数量: {len(result.tool_calls)}")
                if result.tool_calls:
                    for i, tc in enumerate(result.tool_calls):
                        logger.info(f"📊 [社交媒体分析师] - tool_call[{i}]: {tc.get('name', 'unknown')}")

            # 处理情绪分析报告
            if len(result.tool_calls) == 0:
                # 没有工具调用，直接使用LLM的回复
                report = result.content
                logger.info(f"📊 [社交媒体分析师] ✅ 直接回复（无工具调用），长度: {len(report)}")
                logger.debug(f"📊 [DEBUG] 直接回复内容预览: {report[:200]}...")
            else:
                # 有工具调用，执行工具并生成完整分析报告
                logger.info(f"📊 [社交媒体分析师] 🔧 检测到工具调用: {[call.get('name', 'unknown') for call in result.tool_calls]}")

                try:
                    # 执行工具调用
                    from langchain_core.messages import ToolMessage, HumanMessage

                    tool_messages = []
                    for tool_call in result.tool_calls:
                        tool_name = tool_call.get('name')
                        tool_args = tool_call.get('args', {})
                        tool_id = tool_call.get('id')

                        logger.info(f"📊 [社交媒体分析师] 工具执行前，参数: {tool_args}")
                        logger.debug(f"📊 [DEBUG] 执行工具: {tool_name}, 参数: {tool_args}")

                        # 找到对应的工具并执行
                        tool_result = None
                        for tool in tools:
                            current_tool_name = None
                            if hasattr(tool, 'name'):
                                current_tool_name = tool.name
                            elif hasattr(tool, '__name__'):
                                current_tool_name = tool.__name__

                            if current_tool_name == tool_name:
                                try:
                                    tool_result = tool.invoke(tool_args)
                                    logger.info(f"📊 [社交媒体分析师] 工具执行后，结果类型: {type(tool_result)}")
                                    logger.info(f"📊 [社交媒体分析师] ✅ 工具执行成功，结果长度: {len(str(tool_result))}")
                                    break
                                except Exception as tool_error:
                                    logger.error(f"❌ [社交媒体分析师] 工具执行失败: {tool_error}")
                                    tool_result = f"工具执行失败: {str(tool_error)}"

                        if tool_result is None:
                            tool_result = f"未找到工具: {tool_name}"

                        # 创建工具消息
                        tool_message = ToolMessage(
                            content=str(tool_result),
                            tool_call_id=tool_id
                        )
                        tool_messages.append(tool_message)

                    # 基于工具结果生成完整分析报告
                    analysis_prompt = f"""现在请基于上述工具获取的情绪数据，生成详细的社交媒体情绪分析报告。

**分析对象：**
- 公司名称：{company_name}
- 股票代码：{ticker}
- 所属市场：{market_info['market_name']}

**输出格式要求（必须严格遵守）：**

请按照以下专业格式输出报告，使用纯文本标题：

# **{company_name}（{ticker}）社交媒体情绪分析报告**
**分析日期：{current_date}**

---

## 一、情绪指数概览

根据东方财富股吧数据，当前情绪指标如下：

[从工具数据中提取各情绪指数的具体数值，并进行解读]

---

## 二、情绪指数详细分析

### 1. 参与意愿分析
- 当前数值：[提取数值]
- 解读：[根据系数表判断：50+为高活跃，30以下为低活跃]

### 2. 关注度分析
- 当前数值：[提取数值]
- 解读：[根据系数表判断：80+为热点股，70以下为关注下降]

### 3. 综合评价分析
- 当前数值：[提取数值]
- 解读：[根据系数表判断：70+为乐观，50-60为悲观]

### 4. 机构参与度分析
- 当前数值：[提取数值]
- 解读：[根据系数表判断：40+为机构活跃，30以下为散户主导]

---

## 三、情绪组合信号分析

[分析情绪指数的组合情况，识别特殊信号：
- 高关注+低参与意愿 = 观望态度
- 高参与意愿+低机构参与 = 散户主导风险
- 机构活跃+综合评价乐观 = 专业看好]

---

## 四、财经新闻情绪解读

[从工具获取的财经新闻中提取关键信息，分析新闻对情绪的影响]

---

## 五、情绪综合评分与交易建议

**情绪综合评分**：[1-10分，综合各指标给出]

**短期价格影响预测**：
- 预计影响方向：[上涨/下跌/震荡]
- 预计影响幅度：[百分比范围]
- 影响周期：[1-5个交易日]

**交易时机建议**：
[基于情绪分析给出具体建议]

---

⚠️ 注意：必须使用真实数据进行分析；如果数据为空、过期或失败，必须在结构化结论中标注数据状态和缺失数据。

{output_contract}"""

                    # 调用LLM生成最终报告
                    final_messages = state["messages"] + [result] + tool_messages + [HumanMessage(content=analysis_prompt)]
                    final_result = llm.invoke(final_messages)

                    report = final_result.content
                    logger.info(f"📊 [社交媒体分析师] ✅ 分析报告生成完成，长度: {len(report)}")
                    logger.debug(f"📊 [DEBUG] 报告内容预览: {report[:300]}...")

                    # 返回更新后的状态（包含工具消息和报告）
                    return {
                        "messages": [result] + tool_messages + [final_result],
                        "sentiment_report": report,
                        "sentiment_tool_call_count": tool_call_count + 1
                    }

                except Exception as e:
                    logger.error(f"❌ [社交媒体分析师] 工具执行和报告生成失败: {e}")
                    report = f"社交媒体分析师调用工具但分析生成失败: {[call.get('name', 'unknown') for call in result.tool_calls]}，错误: {str(e)}"
                    return {
                        "messages": [result],
                        "sentiment_report": report,
                        "sentiment_tool_call_count": tool_call_count + 1
                    }

        # 🔧 更新工具调用计数器（无工具调用的情况）
        return {
            "messages": [result],
            "sentiment_report": report,
            "sentiment_tool_call_count": tool_call_count + 1
        }

    return social_media_analyst_node
