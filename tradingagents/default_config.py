import os

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_dir": os.path.join(os.path.expanduser("~"), "Documents", "TradingAgents", "data"),
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # LLM settings - 4 档模型配置（按任务复杂度分级）
    "llm_provider": "openai",
    "backend_url": "https://api.openai.com/v1",

    # 4 档 LLM 配置（新增）
    # 1. analyst_llm：工具调用 + 模板化报告（市场/新闻/社交分析师）
    "analyst_llm": "gpt-4o-mini",
    "analyst_model_config": {
        "max_tokens": 4000,
        "temperature": 0.7,
        "timeout": 180,
    },

    # 2. reasoning_llm：估值推理 + 辩论（基本面/Bull/Bear/Risky/Safe）
    "reasoning_llm": "o4-mini",
    "reasoning_model_config": {
        "max_tokens": 4000,
        "temperature": 0.7,
        "timeout": 180,
    },

    # 3. decision_llm：关键决策（最复杂推理：Trader/Research Manager/Risk Judge/Reflector）
    "decision_llm": "o4-mini",
    "decision_model_config": {
        "max_tokens": 4000,
        "temperature": 0.7,
        "timeout": 180,
    },

    # 4. utility_llm：小任务（收敛判断/信号解析）
    "utility_llm": "gpt-4o-mini",
    "utility_model_config": {
        "max_tokens": 2000,
        "temperature": 0.3,
        "timeout": 120,
    },

    # 向后兼容：旧的 2 档配置（保留作为 fallback）
    "deep_think_llm": "o4-mini",
    "quick_think_llm": "gpt-4o-mini",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "horizon": "未来 3 个交易日",
    "max_recur_limit": 100,
    # Tool settings - 从环境变量读取，提供默认值
    "online_tools": os.getenv("ONLINE_TOOLS_ENABLED", "false").lower() == "true",
    "online_news": os.getenv("ONLINE_NEWS_ENABLED", "true").lower() == "true", 
    "realtime_data": os.getenv("REALTIME_DATA_ENABLED", "false").lower() == "true",

    # Note: Database and cache configuration is now managed by .env file and config.database_manager
    # No database/cache settings in default config to avoid configuration conflicts
}
