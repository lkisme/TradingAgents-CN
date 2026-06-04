# TradingAgents/graph/signal_processing.py

from langchain_openai import ChatOpenAI

# 导入统一日志系统和图处理模块日志装饰器
from tradingagents.utils.logging_init import get_logger
from tradingagents.utils.tool_logging import log_graph_module
logger = get_logger("graph.signal_processing")


class SignalProcessor:
    """Processes trading signals to extract actionable decisions."""

    def __init__(self, quick_thinking_llm: ChatOpenAI):
        """Initialize with an LLM for processing."""
        self.quick_thinking_llm = quick_thinking_llm

    @log_graph_module("signal_processing")
    def process_signal(self, full_signal: str, stock_symbol: str = None) -> dict:
        """
        Process a full trading signal to extract structured decision information.

        Args:
            full_signal: Complete trading signal text
            stock_symbol: Stock symbol to determine currency type

        Returns:
            Dictionary containing extracted decision information
        """

        # 验证输入参数
        if not full_signal or not isinstance(full_signal, str) or len(full_signal.strip()) == 0:
            logger.error(f"❌ [SignalProcessor] 输入信号为空或无效: {repr(full_signal)}")
            return {
                'action': '持有',
                'target_price': None,
                'confidence': 0.5,
                'risk_score': 0.5,
                'reasoning': '输入信号无效，默认持有建议'
            }

        # 清理和验证信号内容
        full_signal = full_signal.strip()
        if len(full_signal) == 0:
            logger.error(f"❌ [SignalProcessor] 信号内容为空")
            return {
                'action': '持有',
                'target_price': None,
                'confidence': 0.5,
                'risk_score': 0.5,
                'reasoning': '信号内容为空，默认持有建议'
            }

        # 检测股票类型和货币
        from tradingagents.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(stock_symbol)
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        currency = market_info['currency_name']
        currency_symbol = market_info['currency_symbol']

        logger.info(f"🔍 [SignalProcessor] 处理信号: 股票={stock_symbol}, 市场={market_info['market_name']}, 货币={currency}",
                   extra={'stock_symbol': stock_symbol, 'market': market_info['market_name'], 'currency': currency})

        messages = [
            (
                "system",
                f"""您是一位专业的金融分析助手，负责从交易员的分析报告中提取结构化的投资决策信息。

请从提供的分析报告中提取以下信息，并以JSON格式返回：

{{
    "action": "买入/持有/卖出",
    "target_price": 必须是单一数字({currency}价格)。规则：①区间（如18.50-20.00或18.50至20.00）取中点（19.25）；②多目标价（如"第一目标18.85，第二目标19.50"）取第一目标价（18.85）；③约数（约18.5、≈18.5）去掉前缀取数字（18.5）；④实在无法确定时取报告中最接近目标价语义的数字，不能为null。,
    "confidence": 数字(0-1之间，如果没有明确提及则为0.7),
    "risk_score": 数字(0-1之间，如果没有明确提及则为0.5),
    "reasoning": "决策的主要理由摘要"
}}

请确保：
1. action字段必须是"买入"、"持有"或"卖出"之一（绝对不允许使用英文buy/hold/sell）
2. target_price必须是具体的数字,target_price应该是合理的{currency}价格数字（使用{currency_symbol}符号）
3. confidence和risk_score应该在0-1之间
4. reasoning应该是简洁的中文摘要
5. 所有内容必须使用中文，不允许任何英文投资建议

特别注意：
- 股票代码 {stock_symbol or '未知'} 是{market_info['market_name']}，使用{currency}计价
- 目标价格必须与股票的交易货币一致（{currency_symbol}）

如果某些信息在报告中没有明确提及，请使用合理的默认值。""",
            ),
            ("human", full_signal),
        ]

        # 验证messages内容
        if not messages or len(messages) == 0:
            logger.error(f"❌ [SignalProcessor] messages为空")
            return self._get_default_decision()
        
        # 验证human消息内容
        human_content = messages[1][1] if len(messages) > 1 else ""
        if not human_content or len(human_content.strip()) == 0:
            logger.error(f"❌ [SignalProcessor] human消息内容为空")
            return self._get_default_decision()

        logger.debug(f"🔍 [SignalProcessor] 准备调用LLM，消息数量: {len(messages)}, 信号长度: {len(full_signal)}")

        try:
            response = self.quick_thinking_llm.invoke(messages).content
            logger.debug(f"🔍 [SignalProcessor] LLM响应: {response[:200]}...")

            # 尝试解析JSON响应
            import json
            import re

            # 提取JSON部分
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_text = json_match.group()
                logger.debug(f"🔍 [SignalProcessor] 提取的JSON: {json_text}")
                decision_data = json.loads(json_text)

                # 验证和标准化数据
                action = decision_data.get('action', '持有')
                if action not in ['买入', '持有', '卖出']:
                    # 尝试映射英文和其他变体
                    action_map = {
                        'buy': '买入', 'hold': '持有', 'sell': '卖出',
                        'BUY': '买入', 'HOLD': '持有', 'SELL': '卖出',
                        '购买': '买入', '保持': '持有', '出售': '卖出',
                        'purchase': '买入', 'keep': '持有', 'dispose': '卖出'
                    }
                    action = action_map.get(action, '持有')
                    if action != decision_data.get('action', '持有'):
                        logger.debug(f"🔍 [SignalProcessor] 投资建议映射: {decision_data.get('action')} -> {action}")

                # 处理目标价格，确保正确提取
                target_price = decision_data.get('target_price')
                if target_price is None or target_price == "null" or target_price == "":
                    # 如果JSON中没有目标价格，尝试从reasoning和完整文本中提取
                    reasoning = decision_data.get('reasoning', '')
                    full_text = f"{reasoning} {full_signal}"  # 扩大搜索范围

                    # 优先：目标价关键词 + 区间（取中点）
                    range_patterns = [
                        r'目标价[位格]?[：:]\s*[¥\$]?(\d+(?:\.\d+)?)\s*[-至~到]\s*[¥\$]?(\d+(?:\.\d+)?)',
                        r'目标[：:]\s*[¥\$]?(\d+(?:\.\d+)?)\s*[-至~到]\s*[¥\$]?(\d+(?:\.\d+)?)',
                        r'合理价[位格]?[：:]\s*[¥\$]?(\d+(?:\.\d+)?)\s*[-至~到]\s*[¥\$]?(\d+(?:\.\d+)?)',
                        r'[¥\$](\d+(?:\.\d+)?)\s*[-至~到]\s*[¥\$]?(\d+(?:\.\d+)?)',
                    ]
                    for pattern in range_patterns:
                        m = re.search(pattern, full_text, re.IGNORECASE)
                        if m:
                            try:
                                low, high = float(m.group(1)), float(m.group(2))
                                target_price = round((low + high) / 2, 2)
                                logger.debug(f"🔍 [SignalProcessor] 从区间提取目标价（中点）: {target_price}")
                                break
                            except (ValueError, IndexError):
                                continue

                    # 次优先：目标价关键词 + 单价
                    if target_price is None or target_price == "null" or target_price == "":
                        single_patterns = [
                            r'目标价[位格]?[：:]\s*[¥\$]?(\d+(?:\.\d+)?)',
                            r'\*\*目标价[位格]?\*\*[：:]\s*[¥\$]?(\d+(?:\.\d+)?)',
                            r'目标[：:]\s*[¥\$]?(\d+(?:\.\d+)?)',
                            r'第一目标[位]?\s*[¥\$]?(\d+(?:\.\d+)?)',
                            r'合理[价位格]?[：:]\s*[¥\$]?(\d+(?:\.\d+)?)',
                            r'看[到至]\s*[¥\$]?(\d+(?:\.\d+)?)',
                            r'上涨[到至]\s*[¥\$]?(\d+(?:\.\d+)?)',
                        ]
                        for pattern in single_patterns:
                            m = re.search(pattern, full_text, re.IGNORECASE)
                            if m:
                                try:
                                    target_price = float(m.group(1))
                                    logger.debug(f"🔍 [SignalProcessor] 从关键词提取目标价: {target_price}")
                                    break
                                except (ValueError, IndexError):
                                    continue

                    # 最后兜底：宽泛模式，限制合理价格范围避免误匹配指标数字
                    if target_price is None or target_price == "null" or target_price == "":
                        fallback_patterns = [
                            r'[¥\$](\d+(?:\.\d+)?)',
                            r'(\d+(?:\.\d+)?)元',
                            r'(\d+(?:\.\d+)?)美元',
                            r'(\d+(?:\.\d+)?)\s*[¥\$]',
                        ]
                        for pattern in fallback_patterns:
                            for m in re.finditer(pattern, full_text, re.IGNORECASE):
                                try:
                                    val = float(m.group(1))
                                    # 过滤明显非股价的数字（PE/RSI/百分比等通常<100且无货币符号）
                                    if is_china and 0.5 <= val <= 10000:
                                        target_price = val
                                        logger.debug(f"🔍 [SignalProcessor] 宽泛模式提取目标价: {target_price}")
                                        break
                                    elif not is_china and 0.1 <= val <= 100000:
                                        target_price = val
                                        logger.debug(f"🔍 [SignalProcessor] 宽泛模式提取目标价: {target_price}")
                                        break
                                except (ValueError, IndexError):
                                    continue
                            if target_price is not None and target_price != "null":
                                break

                    # 如果仍然没有找到价格，尝试智能推算
                    if target_price is None or target_price == "null" or target_price == "":
                        target_price = self._smart_price_estimation(full_text, action, is_china)
                        if target_price:
                            logger.debug(f"🔍 [SignalProcessor] 智能推算目标价格: {target_price}")
                        else:
                            target_price = None
                            logger.warning(f"🔍 [SignalProcessor] 未能提取到目标价格，设置为None")
                else:
                    # 确保价格是数值类型（支持区间、约数、多目标价等格式）
                    try:
                        target_price = self._parse_price_string(target_price)
                        logger.debug(f"🔍 [SignalProcessor] 处理后的目标价格: {target_price}")
                    except (ValueError, TypeError):
                        target_price = None
                        logger.warning(f"🔍 [SignalProcessor] 价格转换失败，设置为None")

                result = {
                    'action': action,
                    'target_price': target_price,
                    'confidence': float(decision_data.get('confidence', 0.7)),
                    'risk_score': float(decision_data.get('risk_score', 0.5)),
                    'reasoning': decision_data.get('reasoning', '基于综合分析的投资建议'),
                    'stop_loss': decision_data.get('stop_loss'),
                    'risk_reward_ratio': decision_data.get('risk_reward_ratio'),
                    'position_size': decision_data.get('position_size'),
                    'horizon': decision_data.get('horizon'),
                    'invalidation': decision_data.get('invalidation'),
                }
                logger.info(f"🔍 [SignalProcessor] 处理结果: {result}",
                           extra={'action': result['action'], 'target_price': result['target_price'],
                                 'confidence': result['confidence'], 'stock_symbol': stock_symbol})
                return result
            else:
                # 如果无法解析JSON，使用简单的文本提取
                return self._extract_simple_decision(response)

        except Exception as e:
            logger.error(f"信号处理错误: {e}", exc_info=True, extra={'stock_symbol': stock_symbol})
            # 回退到简单提取
            return self._extract_simple_decision(full_signal)

    def _parse_price_string(self, price_str) -> float:
        """从各种格式的价格字符串中提取单一数值。
        支持：区间取中点、多目标价取第一个、约数去前缀、港元/港币清洗。
        """
        import re
        if price_str is None:
            return None
        if isinstance(price_str, (int, float)):
            return float(price_str)

        s = str(price_str).strip()

        # 清洗货币符号和常见单位
        for unit in ['港元', '港币', 'HKD', 'hkd', '美元', 'USD', 'usd', '人民币', '元', '$', '¥', '￥']:
            s = s.replace(unit, '')
        s = s.strip()

        # 多目标价：取第一个数字（"第一目标18.85，第二目标19.50"）
        first_target = re.search(r'第一[目标位]+\s*(\d+(?:\.\d+)?)', s)
        if first_target:
            return float(first_target.group(1))

        # 区间格式：取中点（"18.50 - 20.00" / "18.50至20.00" / "18.50~20.00"）
        range_match = re.search(r'(\d+(?:\.\d+)?)\s*[-至~到]\s*(\d+(?:\.\d+)?)', s)
        if range_match:
            low = float(range_match.group(1))
            high = float(range_match.group(2))
            return round((low + high) / 2, 2)

        # 约数：去前缀（"约18.5" / "≈18.5" / "~18.5"）
        approx_match = re.search(r'[约≈~＝≒]\s*(\d+(?:\.\d+)?)', s)
        if approx_match:
            return float(approx_match.group(1))

        # 括号注释：取括号外的数字（"18.85（第一目标）"）
        s_no_bracket = re.sub(r'[（(][^）)]*[）)]', '', s).strip()

        # 直接取第一个数字
        num_match = re.search(r'(\d+(?:\.\d+)?)', s_no_bracket or s)
        if num_match:
            return float(num_match.group(1))

        return None

    def _smart_price_estimation(self, text: str, action: str, is_china: bool) -> float:
        """智能价格推算方法"""
        import re
        
        # 尝试从文本中提取当前价格和涨跌幅信息
        current_price = None
        percentage_change = None
        
        # 提取当前价格
        current_price_patterns = [
            r'当前价[格位]?[：:]?\s*[¥\$]?(\d+(?:\.\d+)?)',
            r'现价[：:]?\s*[¥\$]?(\d+(?:\.\d+)?)',
            r'股价[：:]?\s*[¥\$]?(\d+(?:\.\d+)?)',
            r'价格[：:]?\s*[¥\$]?(\d+(?:\.\d+)?)',
        ]
        
        for pattern in current_price_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    current_price = float(match.group(1))
                    break
                except ValueError:
                    continue
        
        # 提取涨跌幅信息
        percentage_patterns = [
            r'上涨\s*(\d+(?:\.\d+)?)%',
            r'涨幅\s*(\d+(?:\.\d+)?)%',
            r'增长\s*(\d+(?:\.\d+)?)%',
            r'(\d+(?:\.\d+)?)%\s*的?上涨',
        ]
        
        for pattern in percentage_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    percentage_change = float(match.group(1)) / 100
                    break
                except ValueError:
                    continue
        
        # 基于动作和信息推算目标价
        if current_price and percentage_change:
            if action == '买入':
                return round(current_price * (1 + percentage_change), 2)
            elif action == '卖出':
                return round(current_price * (1 - percentage_change), 2)
        
        # 如果有当前价格但没有涨跌幅，使用默认估算
        if current_price:
            if action == '买入':
                # 买入建议默认10-20%涨幅
                multiplier = 1.15 if is_china else 1.12
                return round(current_price * multiplier, 2)
            elif action == '卖出':
                # 卖出建议默认5-10%跌幅
                multiplier = 0.95 if is_china else 0.92
                return round(current_price * multiplier, 2)
            else:  # 持有
                # 持有建议使用当前价格
                return current_price
        
        return None

    def _extract_simple_decision(self, text: str) -> dict:
        """简单的决策提取方法作为备用"""
        import re

        # 提取动作
        action = '持有'  # 默认
        if re.search(r'买入|BUY', text, re.IGNORECASE):
            action = '买入'
        elif re.search(r'卖出|SELL', text, re.IGNORECASE):
            action = '卖出'
        elif re.search(r'持有|HOLD', text, re.IGNORECASE):
            action = '持有'

        # 尝试提取目标价格（复用 _parse_price_string，三级优先级）
        target_price = None

        # 优先：目标价关键词 + 区间 → 取中点
        import re
        for pattern in [
            r'目标价[位格]?[：:]\s*[¥\$]?(\d+(?:\.\d+)?)\s*[-至~到]\s*[¥\$]?(\d+(?:\.\d+)?)',
            r'目标[：:]\s*[¥\$]?(\d+(?:\.\d+)?)\s*[-至~到]\s*[¥\$]?(\d+(?:\.\d+)?)',
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                try:
                    target_price = round((float(m.group(1)) + float(m.group(2))) / 2, 2)
                    break
                except (ValueError, IndexError):
                    continue

        # 次优先：目标价关键词 + 单价
        if target_price is None:
            for pattern in [
                r'目标价[位格]?[：:]\s*[¥\$]?(\d+(?:\.\d+)?)',
                r'\*\*目标价[位格]?\*\*[：:]\s*[¥\$]?(\d+(?:\.\d+)?)',
                r'第一目标[位]?\s*[¥\$]?(\d+(?:\.\d+)?)',
                r'目标[：:]\s*[¥\$]?(\d+(?:\.\d+)?)',
                r'看[到至]\s*[¥\$]?(\d+(?:\.\d+)?)',
            ]:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    try:
                        target_price = float(m.group(1))
                        break
                    except (ValueError, IndexError):
                        continue

        # 最后兜底：用 _parse_price_string 处理第一个货币符号价格
        if target_price is None:
            m = re.search(r'[¥\$](\d+(?:\.\d+)?(?:\s*[-至~到]\s*\d+(?:\.\d+)?)?)', text)
            if m:
                target_price = self._parse_price_string(m.group(1))

        # 如果没有找到价格，尝试智能推算
        if target_price is None:
            # 检测股票类型
            is_china = True  # 默认假设是A股，实际应该从上下文获取
            target_price = self._smart_price_estimation(text, action, is_china)

        return {
            'action': action,
            'target_price': target_price,
            'confidence': 0.7,
            'risk_score': 0.5,
            'reasoning': '基于综合分析的投资建议',
            'stop_loss': None,
            'risk_reward_ratio': None,
            'position_size': None,
            'horizon': None,
            'invalidation': None,
        }

    def _get_default_decision(self) -> dict:
        """返回默认的投资决策"""
        return {
            'action': '持有',
            'target_price': None,
            'confidence': 0.5,
            'risk_score': 0.5,
            'reasoning': '输入数据无效，默认持有建议',
            'stop_loss': None,
            'risk_reward_ratio': None,
            'position_size': None,
            'horizon': None,
            'invalidation': None,
        }
