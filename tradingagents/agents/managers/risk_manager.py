import time
import json

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
from tradingagents.agents.utils.instrument_utils import build_instrument_context
from tradingagents.agents.utils.trade_decision import TradeDecision
logger = get_logger("default")


def create_risk_manager(llm, memory):
    def risk_manager_node(state) -> dict:

        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        horizon = state.get("horizon", "未来 3 个交易日")

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        combined_report_summary = state.get("combined_report_summary", "")
        trader_plan = state["trader_investment_plan"]

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

        prompt = f"""作为风险管理委员会主席和辩论主持人，您的目标是评估三位风险分析师——激进、中性和安全/保守——之间的辩论，并确定交易员的最佳行动方案。您的决策必须产生明确的建议：买入、卖出或持有。力求清晰和果断。当数据不足以支持买入或卖出时，持有/弃权是合理的选择。

决策指导原则：
1. **总结关键论点**：提取每位分析师的最强观点，重点关注与背景的相关性。
2. **提供理由**：用辩论中的直接引用和反驳论点支持您的建议。
3. **完善交易员计划**：从交易员的原始计划**{trader_plan}**开始，根据分析师的见解进行调整。
4. **参考历史经验**：以下是过去类似情境的记录（含实际收益结果）。这些记录仅供参考，不代表历史决策正确。请基于当前数据和辩论独立判断，避免过度依赖历史模式。

交付成果：
- 明确且可操作的建议：买入、卖出或持有。
- 基于辩论和过去反思的详细推理。
- 具体目标价格：给出明确的数值或区间（如 XX 元或 XX-XX 元）。如数据不足，可标注低置信度。
- 止损价格：建议的止损价位
- 盈亏比：预期收益与预期损失的比值
- 建议仓位：占总资金的比例（0-1）
- 持有期：{horizon}
- 失效条件：什么情况下应推翻当前判断

⚠️ 决策一致性复核要求：
1. 必须校验建议方向和目标价是否匹配：买入建议目标价必须高于现价，卖出建议必须低于现价
2. 必须校验目标价逻辑和给出的理由是否自洽：不能出现逻辑看大涨但目标价仅微涨、或者逻辑看空但目标价接近现价的自相矛盾情况
3. 必须校验盈亏比合理性：收益必须大于潜在风险，禁止输出盈亏比<1的建议
如果发现上游决策有明显自相矛盾的地方，必须明确指出并修正。

综合分析摘要：
{combined_report_summary}

标的约束：
{instrument_context}

---

**分析师辩论历史：**
{history}

---

专注于可操作的见解和持续改进。建立在过去经验教训的基础上，批判性地评估所有观点，确保每个决策都能带来更好的结果。请用中文撰写所有分析内容和建议。"""

        # 📊 统计 prompt 大小
        prompt_length = len(prompt)
        # 粗略估算 token 数量（中文约 1.5-2 字符/token，英文约 4 字符/token）
        estimated_tokens = int(prompt_length / 1.8)  # 保守估计

        logger.info(f"📊 [Risk Manager] Prompt 统计:")
        logger.info(f"   - 辩论历史长度: {len(history)} 字符")
        logger.info(f"   - 交易员计划长度: {len(trader_plan)} 字符")
        logger.info(f"   - 历史记忆长度: {len(past_memory_str)} 字符")
        logger.info(f"   - 总 Prompt 长度: {prompt_length} 字符")
        logger.info(f"   - 估算输入 Token: ~{estimated_tokens} tokens")

        # 增强的LLM调用，包含错误处理和重试机制
        max_retries = 3
        retry_count = 0
        response_content = ""

        while retry_count < max_retries:
            try:
                logger.info(f"🔄 [Risk Manager] 调用LLM生成交易决策 (尝试 {retry_count + 1}/{max_retries})")

                # ⏱️ 记录开始时间
                start_time = time.time()

                response = llm.invoke(prompt)

                # ⏱️ 记录结束时间
                elapsed_time = time.time() - start_time
                
                if response and hasattr(response, 'content') and response.content:
                    response_content = response.content.strip()

                    # 📊 统计响应信息
                    response_length = len(response_content)
                    estimated_output_tokens = int(response_length / 1.8)

                    # 尝试获取实际的 token 使用情况（如果 LLM 返回了）
                    usage_info = ""
                    if hasattr(response, 'response_metadata') and response.response_metadata:
                        metadata = response.response_metadata
                        if 'token_usage' in metadata:
                            token_usage = metadata['token_usage']
                            usage_info = f", 实际Token: 输入={token_usage.get('prompt_tokens', 'N/A')} 输出={token_usage.get('completion_tokens', 'N/A')} 总计={token_usage.get('total_tokens', 'N/A')}"

                    logger.info(f"⏱️ [Risk Manager] LLM调用耗时: {elapsed_time:.2f}秒")
                    logger.info(f"📊 [Risk Manager] 响应统计: {response_length} 字符, 估算~{estimated_output_tokens} tokens{usage_info}")

                    if len(response_content) > 10:  # 确保响应有实质内容
                        logger.info(f"✅ [Risk Manager] LLM调用成功")
                        break
                    else:
                        logger.warning(f"⚠️ [Risk Manager] LLM响应内容过短: {len(response_content)} 字符")
                        response_content = ""
                else:
                    logger.warning(f"⚠️ [Risk Manager] LLM响应为空或无效")
                    response_content = ""

            except Exception as e:
                elapsed_time = time.time() - start_time
                logger.error(f"❌ [Risk Manager] LLM调用失败 (尝试 {retry_count + 1}): {str(e)}")
                logger.error(f"⏱️ [Risk Manager] 失败前耗时: {elapsed_time:.2f}秒")
                response_content = ""
            
            retry_count += 1
            if retry_count < max_retries and not response_content:
                logger.info(f"🔄 [Risk Manager] 等待2秒后重试...")
                time.sleep(2)
        
        # 如果所有重试都失败，生成默认决策
        if not response_content:
            logger.error(f"❌ [Risk Manager] 所有LLM调用尝试失败，使用默认决策")
            response_content = f"""**默认建议：持有**

由于技术原因无法生成详细分析，基于当前市场状况和风险控制原则，建议对{company_name}采取持有策略。

**理由：**
1. 市场信息不足，避免盲目操作
2. 保持现有仓位，等待更明确的市场信号
3. 控制风险，避免在不确定性高的情况下做出激进决策

**建议：**
- 密切关注市场动态和公司基本面变化
- 设置合理的止损和止盈位
- 等待更好的入场或出场时机

注意：此为系统默认建议，建议结合人工分析做出最终决策。"""

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

        logger.info(f"📋 [Risk Manager] 最终决策生成完成，内容长度: {len(response_content)} 字符")
        
        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": response_content,
        }

    return risk_manager_node


def create_risk_manager_structured(llm, memory):
    """Create Risk Manager node with structured output support.

    This version uses LangChain's with_structured_output() for providers
    that support it (OpenAI, Anthropic, Google). Returns a TradeDecision
    directly without needing SignalProcessor parsing.
    """
    def risk_manager_structured_node(state) -> dict:

        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        horizon = state.get("horizon", "未来 3 个交易日")

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        combined_report_summary = state.get("combined_report_summary", "")
        trader_plan = state["trader_investment_plan"]

        curr_situation = combined_report_summary

        # Memory lookup
        if memory is not None:
            past_memories = memory.get_memories(curr_situation, n_matches=2)
        else:
            logger.warning(f"⚠️ [Risk Manager Structured] memory为None，跳过历史记忆检索")
            past_memories = []

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        # Same prompt as regular risk_manager, with JSON format hint for structured output
        prompt = f"""请以JSON格式输出您的交易决策。作为风险管理委员会主席和辩论主持人，您的目标是评估三位风险分析师——激进、中性和安全/保守——之间的辩论，并确定交易员的最佳行动方案。您的决策必须产生明确的建议：买入、卖出或持有。力求清晰和果断。当数据不足以支持买入或卖出时，持有/弃权是合理的选择。

决策指导原则：
1. **总结关键论点**：提取每位分析师的最强观点，重点关注与背景的相关性。
2. **提供理由**：用辩论中的直接引用和反驳论点支持您的建议。
3. **完善交易员计划**：从交易员的原始计划**{trader_plan}**开始，根据分析师的见解进行调整。
4. **参考历史经验**：以下是过去类似情境的记录（含实际收益结果）。这些记录仅供参考，不代表历史决策正确。请基于当前数据和辩论独立判断，避免过度依赖历史模式。

交付成果：
- 明确且可操作的建议：买入、卖出或持有。
- 基于辩论和过去反思的详细推理。
- 具体目标价格：给出明确的数值或区间（如 XX 元或 XX-XX 元）。如数据不足，可标注低置信度。
- 止损价格：建议的止损价位
- 盈亏比：预期收益与预期损失的比值
- 建议仓位：占总资金的比例（0-1）
- 持有期：{horizon}
- 失效条件：什么情况下应推翻当前判断

⚠️ 决策一致性复核要求：
1. 必须校验建议方向和目标价是否匹配：买入建议目标价必须高于现价，卖出建议必须低于现价
2. 必须校验目标价逻辑和给出的理由是否自洽：不能出现逻辑看大涨但目标价仅微涨、或者逻辑看空但目标价接近现价的自相矛盾情况
3. 必须校验盈亏比合理性：收益必须大于潜在风险，禁止输出盈亏比<1的建议
如果发现上游决策有明显自相矛盾的地方，必须明确指出并修正。

综合分析摘要：
{combined_report_summary}

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

            if decision.stop_loss is not None:
                response_content += f"\n\n**止损价格：** {decision.stop_loss}"
            if decision.risk_reward_ratio is not None:
                response_content += f"\n\n**盈亏比：** {decision.risk_reward_ratio}"
            if decision.position_size is not None:
                response_content += f"\n\n**建议仓位：** {decision.position_size:.0%}"
            if decision.horizon:
                response_content += f"\n\n**持有期：** {decision.horizon}"
            if decision.invalidation:
                response_content += f"\n\n**失效条件：** {decision.invalidation}"

        except Exception as e:
            logger.error(f"❌ [Risk Manager Structured] 结构化输出失败: {e}")
            logger.info(f"📊 [Risk Manager Structured] 降级到普通模式，使用标准LLM调用生成完整分析...")

            # 降级处理：调用普通模式的LLM生成完整分析报告
            # 复用 create_risk_manager 的完整逻辑
            max_retries = 3
            retry_count = 0
            response_content = ""

            while retry_count < max_retries:
                try:
                    logger.info(f"🔄 [Risk Manager Structured -> Fallback] 调用LLM生成交易决策 (尝试 {retry_count + 1}/{max_retries})")
                    start_time = time.time()

                    # 使用普通LLM调用（不使用结构化输出）
                    response = llm.invoke(prompt)

                    elapsed_time = time.time() - start_time

                    if response and hasattr(response, 'content') and response.content:
                        response_content = response.content.strip()
                        response_length = len(response_content)

                        logger.info(f"⏱️ [Risk Manager Structured -> Fallback] LLM调用耗时: {elapsed_time:.2f}秒")
                        logger.info(f"📊 [Risk Manager Structured -> Fallback] 响应统计: {response_length} 字符")

                        if len(response_content) > 10:
                            logger.info(f"✅ [Risk Manager Structured -> Fallback] LLM调用成功，生成完整分析")
                            break
                        else:
                            logger.warning(f"⚠️ [Risk Manager Structured -> Fallback] LLM响应内容过短: {len(response_content)} 字符")
                            response_content = ""
                    else:
                        logger.warning(f"⚠️ [Risk Manager Structured -> Fallback] LLM响应为空或无效")
                        response_content = ""

                except Exception as fallback_e:
                    elapsed_time = time.time() - start_time
                    logger.error(f"❌ [Risk Manager Structured -> Fallback] LLM调用失败 (尝试 {retry_count + 1}): {str(fallback_e)}")
                    response_content = ""

                retry_count += 1
                if retry_count < max_retries and not response_content:
                    logger.info(f"🔄 [Risk Manager Structured -> Fallback] 等待2秒后重试...")
                    time.sleep(2)

            # 如果降级模式的LLM调用也全部失败，才使用默认决策
            if not response_content:
                logger.error(f"❌ [Risk Manager Structured -> Fallback] 所有LLM调用尝试失败，使用默认决策")
                response_content = f"""**默认建议：持有**

由于技术原因无法生成详细分析，基于当前市场状况和风险控制原则，建议对{company_name}采取持有策略。

**理由：**
1. 市场信息不足，避免盲目操作
2. 保持现有仓位，等待更明确的市场信号
3. 控制风险，避免在不确定性高的情况下做出激进决策

**建议：**
- 密切关注市场动态和公司基本面变化
- 设置合理的止损和止盈位
- 等待更好的入场或出场时机

注意：此为系统默认建议，建议结合人工分析做出最终决策。原因：结构化输出失败({str(e)})，降级模式调用也失败。"""

            # 降级模式下无法生成结构化数据，使用空的decision_dict
            decision_dict = {
                "action": "持有",
                "target_price": None,
                "confidence": 0.5,
                "risk_score": 0.5,
                "reasoning": f"结构化输出失败，降级使用普通模式生成文本分析。原始错误: {str(e)}",
                "stop_loss": None,
                "risk_reward_ratio": None,
                "position_size": None,
                "horizon": None,
                "invalidation": None,
            }
            logger.info(f"📋 [Risk Manager Structured -> Fallback] 最终决策生成完成，内容长度: {len(response_content)} 字符")

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
