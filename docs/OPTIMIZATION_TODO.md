# TradingAgents-CN 优化待办清单

> 最后更新：2025-05-10
> 状态图例：🔴 未开始 | 🟡 设计中 | 🟢 进行中 | ✅ 已完成 | ⏸️ 搁置

---

## 🔴 待优化项

<!-- 在此添加新的优化项 -->

### [#1] Embedding 模型独立 Provider 重构
- **状态：** 🟡 设计已评审，待实施
- **优先级：** P1
- **模块：** `tradingagents/agents/utils/memory.py` → 新建 `tradingagents/agents/utils/embedding/`
- **设计文档：** `docs/embedding-provider-design.md`
- **描述：**
  - 当前 `FinancialSituationMemory` 中 embedding 选择逻辑与 LLM provider 紧耦合，大量 if-elif-else 散落在 `__init__` 和 `get_embedding` 中（约 200 行）
  - 无法灵活组合，例如 "DeepSeek 主模型 + 阿里百炼 embedding"
  - 新增 embedding provider 需要修改多处代码
- **设计评审意见（2025-05-10）：**
  - ✅ 整体架构合理：`EmbeddingProvider` 基类 → 各具体 Provider → `EmbeddingManager` 管理 + fallback
  - ✅ 接口设计清晰：`get_embeddings()`, `get_embedding_dimension()`, `is_available()`, `get_provider_name()`, `get_model_name()`
  - ⚠️ **需改进点：**
    1. **批量接口缺失**：设计文档的 `get_embeddings(List[str])` 是批量接口，但现有 memory.py 用的是单文本 `get_embedding(text)`。需确认 DashScope `TextEmbedding.call()` 是否支持批量输入——如果支持，应优先批量调用减少 API 次数
    2. **维度一致性检查**：切换 provider 时 ChromaDB 集合维度会不匹配，需要在 Manager 中增加 `_handle_dimension_mismatch()` 逻辑（新建集合 or 重建数据）
    3. **配置三级来源**：设计文档提到了环境变量 + config.yaml + MongoDB，但 MongoDB 动态配置的优先级和热更新机制未详细说明。建议：环境变量 > MongoDB > 配置文件 > 默认值
    4. **LocalEmbeddingProvider 缺失实现**：设计文档列了但没给代码。建议用 `sentence-transformers`，模型推荐 `BAAI/bge-large-zh-v1.5`（中文效果好）
    5. **成本监控部分被截断**：第 500 行后的内容未读完，需要补充 cost tracking 设计
    6. **QwenEmbeddingProvider 与 DashScopeEmbeddingProvider 重复**：Qwen 走的就是百炼 API，两个 provider 本质相同，建议合并为一个，通过 model 参数区分
  - ✅ 推荐实施顺序：基类 → DashScope/OpenAI Provider → Manager → 重构 memory.py → 配置集成 → 测试
- **涉及文件改动：**
  | 文件 | 操作 |
  |------|------|
  | `tradingagents/agents/utils/embedding/base.py` | 新建 - 抽象基类 |
  | `tradingagents/agents/utils/embedding/providers/dashscope.py` | 新建 |
  | `tradingagents/agents/utils/embedding/providers/openai.py` | 新建 |
  | `tradingagents/agents/utils/embedding/providers/local.py` | 新建 - sentence-transformers |
  | `tradingagents/agents/utils/embedding/manager.py` | 新建 - EmbeddingManager |
  | `tradingagents/agents/utils/embedding/config.py` | 新建 - 配置解析 |
  | `tradingagents/agents/utils/memory.py` | 重构 - 移除散落的 embedding 逻辑 |
  | `.env.example` | 新增 EMBEDDING_* 配置项 |
  | `tests/test_embedding_provider.py` | 新建 - 单元测试 |
- **进度：**

---

### [#2] 支持中文社交媒体分析
- **状态：** 🔴 未开始，待方案设计
- **优先级：** P1
- **模块：** `tradingagents/dataflows/news/chinese_finance.py`, `tradingagents/agents/analysts/social_media_analyst.py`
- **描述：**
  - 当前社交媒体分析的核心数据源 `chinese_finance.py` 基本是**空壳/模拟数据**：
    - `_search_finance_news()` → 返回硬编码 mock 数据
    - `_get_stock_forum_sentiment()` → 直接返回空数据 + "受限"提示
    - `_get_media_coverage()` → 返回空列表
    - `_analyze_text_sentiment()` → 仅 9 个正面词 + 9 个负面词的关键词匹配
    - `_get_company_chinese_name()` → 仅有 6 个美股映射
  - `social_media_analyst.py` 的 prompt 设计已到位（针对中国市场），但实际调用的 `get_stock_sentiment_unified` 工具底层数据质量很低
  - 需要接入真实的中国社交媒体/财经平台数据源
- **需要支持的平台：**
  - **雪球 (Xueqiu)** — 投资社区，已有 `xueqiu-stock` skill
  - **东方财富股吧** — 散户讨论热度
  - **微博财经** — 大V观点、热点事件
  - **财联社/新浪财经** — 实时财经快讯
  - **同花顺** — 投资者情绪指标
  - **知乎投资话题** — 深度讨论
- **方案设计要点：**
  1. **数据接入层**：为每个平台建立独立的数据 provider（API/爬虫/RSS）
  2. **情绪分析引擎**：替换当前的关键词匹配，使用 LLM 或专用中文情感模型
  3. **缓存策略**：社交媒体数据时效性强，需设置合理的 TTL
  4. **合规性**：注意各平台的 robots.txt 和使用条款
  5. **降级策略**：某平台不可用时自动降级到其他数据源
- **进度：**

---

## 项目概况

### 核心模块结构
| 目录 | 说明 |
|------|------|
| `tradingagents/` | 核心后端（agents、LLM、数据流、图结构） |
| `tradingagents/llm_clients/` | 多厂商 LLM 客户端 |
| `tradingagents/llm_adapters/` | LLM 适配器 |
| `tradingagents/dataflows/` | 数据流服务 |
| `tradingagents/graph/` | LangGraph 交易图 |
| `tradingagents/config/` | 配置管理 |
| `app/` | Streamlit Web 应用 |
| `frontend/` | Vue 前端 |
| `cli/` | CLI 工具 |
| `scripts/` | 运维/构建/分析脚本 |
| `docs/` | 文档 |

### 技术栈
- **后端：** Python + LangGraph + 多 LLM 供应商
- **前端：** Vue.js + Streamlit
- **部署：** Docker / Docker Compose
- **数据：** MongoDB + 多种数据源（Tushare、AKShare、BaoStock）

---

## 变更记录

| 日期 | 操作 |
|------|------|
| 2025-05-10 | 创建优化追踪文件 |
