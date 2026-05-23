# Social Analyst 工具调用后报告生成修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复社交媒体分析师在工具调用后无法生成情绪分析报告的问题。

**Architecture:** 参考 Market Analyst 的成熟模式，在 Social Analyst 内部添加工具执行和报告生成逻辑，而不是依赖 LangGraph 的 ToolNode 循环（该循环存在短路问题）。

**Tech Stack:** LangChain, LangGraph, 通义千问/DashScope OpenAI兼容模式

---

## 问题根因

当非 Google 模型（如通义千问）调用工具时：
1. LLM 返回 `tool_calls > 0`
2. 当前代码设置 `report = ""`（第227-229行）
3. LangGraph ToolNode 循环被短路（第二次 Analyst 执行只用了 0.01秒）
4. 工具数据（2922字符）无法转化为报告

**对比 Market Analyst**：Market Analyst 在检测到 `tool_calls > 0` 时会手动执行工具、构建分析提示词、再次调用 LLM 生成报告。

---

## 文件结构

| 文件 | 修改内容 |
|------|----------|
| `tradingagents/agents/analysts/social_media_analyst.py` | 添加工具执行和报告生成逻辑（第223-236行） |

---

### Task 1: 添加非Google模型的工具执行和报告生成逻辑

**Files:**
- Modify: `tradingagents/agents/analysts/social_media_analyst.py:223-236`

**当前代码（问题所在）：**
```python
else:
    # 非Google模型的处理逻辑
    logger.debug(f"📊 [DEBUG] 非Google模型 ({llm.__class__.__name__})，使用标准处理逻辑")
    
    report = ""
    if len(result.tool_calls) == 0:
        report = result.content

# 🔧 更新工具调用计数器
return {
    "messages": [result],
    "sentiment_report": report,
    "sentiment_tool_call_count": tool_call_count + 1
}
```

- [ ] **Step 1: 替换非Google模型处理逻辑**

将第223-236行替换为以下完整代码：

```python
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

⚠️ 注意：必须使用真实数据进行分析，不允许回复"无法评估"或"需要更多数据"。"""

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
```

- [ ] **Step 2: 重新构建 backend Docker 镜像**

```bash
cd /root/workspace/TradingAgents-CN
docker build -f Dockerfile.backend -t tradingagents-backend:v1.0.1-local .
```

- [ ] **Step 3: 重启 backend 容器**

```bash
cd /root/tradingagents-demo
docker-compose -f docker-compose.hub.nginx.yml restart backend
```

- [ ] **Step 4: 提交分析任务验证修复**

在前端提交一个包含社媒分析师的 A股 分析任务（如 000568），检查：
1. 日志中是否有 `📊 [社交媒体分析师] 🔧 检测到工具调用`
2. 日志中是否有 `📊 [社交媒体分析师] ✅ 分析报告生成完成`
3. `sentiment_report.md` 文件大小是否 > 0

- [ ] **Step 5: 检查日志确认工具执行和报告生成**

```bash
docker logs tradingagents-backend --tail 200 2>&1 | grep -E "(社交媒体分析师|sentiment_report)"
```

预期输出：
- `✅ 工具执行成功，结果长度: [数字]`
- `✅ 分析报告生成完成，长度: [数字]`
- `sentiment_report: [数字] 字符`（数字 > 0）

- [ ] **Step 6: 验证报告文件内容**

```bash
docker exec tradingagents-backend cat /app/data/analysis_results/000568/[日期]/reports/sentiment_report.md
```

预期：包含完整的情绪分析报告，包括情绪指数数值、解读、财经新闻分析等。

---

### Task 2: 优化日志输出（可选）

**Files:**
- Modify: `tradingagents/agents/analysts/social_media_analyst.py`

- [ ] **Step 1: 添加更详细的工具执行日志**

在工具执行部分添加调试日志，帮助追踪问题：

```python
logger.info(f"📊 [社交媒体分析师] 工具执行前，参数: {tool_args}")
logger.info(f"📊 [社交媒体分析师] 工具执行后，结果类型: {type(tool_result)}")
```

---

## 验收标准

1. **功能验收**：
   - 提交包含社媒分析师的分析任务
   - `sentiment_report.md` 文件大小 > 500 字符
   - 报告包含情绪指数数值和解读

2. **日志验收**：
   - 日志显示 `检测到工具调用`
   - 日志显示 `工具执行成功`
   - 日志显示 `分析报告生成完成`

3. **对比验证**：
   - 包含社媒分析师的报告有情绪分析内容
   - 不包含社媒分析师的报告缺少情绪分析部分

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 工具执行失败 | 报告为空 | 已添加异常处理，返回错误信息 |
| LLM 生成超时 | 报告不完整 | 使用 timeout 参数控制 |
| 消息过长 | Token 超限 | 工具返回 2922 字符，在合理范围内 |

---

## 自检清单

- [x] 每个步骤包含完整代码
- [x] 每个步骤有验证命令
- [x] 无占位符（TBD、TODO等）
- [x] 文件路径精确
- [x] 任务粒度适中（2-5分钟每步）