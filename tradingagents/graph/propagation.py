# TradingAgents/graph/propagation.py

from typing import Dict, Any

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)


def _resolve_company_name(ticker: str) -> str:
    """Resolve human-readable company name from ticker.

    Args:
        ticker: Stock ticker code (e.g., '600519', '00700.HK', 'AAPL')

    Returns:
        Company name string, or ticker itself as fallback
    """
    from tradingagents.utils.stock_utils import StockUtils

    market_info = StockUtils.get_market_info(ticker)

    try:
        if market_info['is_china']:
            from tradingagents.dataflows.interface import get_china_stock_info_unified
            stock_info = get_china_stock_info_unified(ticker)
            if stock_info and "股票名称:" in stock_info:
                name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
                logger.info(f"✅ [Propagator] 成功获取A股名称: {ticker} -> {name}")
                return name
        elif market_info['is_hk']:
            from tradingagents.dataflows.providers.hk.improved_hk import get_hk_company_name_improved
            name = get_hk_company_name_improved(ticker)
            logger.info(f"✅ [Propagator] 成功获取港股名称: {ticker} -> {name}")
            return name
        elif market_info['is_us']:
            us_stock_names = {
                'AAPL': '苹果公司', 'TSLA': '特斯拉', 'NVDA': '英伟达',
                'MSFT': '微软', 'GOOGL': '谷歌', 'AMZN': '亚马逊',
                'META': 'Meta', 'NFLX': '奈飞'
            }
            name = us_stock_names.get(ticker.upper(), f"美股{ticker}")
            logger.info(f"✅ [Propagator] 使用美股映射: {ticker} -> {name}")
            return name
    except Exception as e:
        logger.error(f"❌ [Propagator] 获取公司名称失败: {e}")

    return ticker


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self, ticker: str, trade_date: str
    ) -> Dict[str, Any]:
        """Create the initial state for the agent graph."""
        from langchain_core.messages import HumanMessage

        # Resolve company name once at initialization
        company_name = _resolve_company_name(ticker)

        # 🔥 修复：创建明确的分析请求消息，而不是只传递股票代码
        # 这样可以确保所有LLM（包括DeepSeek）都能理解任务
        analysis_request = f"请对股票 {company_name} 进行全面分析，交易日期为 {trade_date}。"

        return {
            "messages": [HumanMessage(content=analysis_request)],
            "company_of_interest": ticker,
            "company_name": company_name,
            "trade_date": str(trade_date),
            "investment_debate_state": InvestDebateState(
                {"history": "", "current_response": "", "count": 0}
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "history": "",
                    "current_risky_response": "",
                    "current_safe_response": "",
                    "current_neutral_response": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
        }

    def get_graph_args(self, use_progress_callback: bool = False) -> Dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            use_progress_callback: If True, use 'updates' mode for node-level progress tracking.
                                  If False, use 'values' mode for complete state updates.
        """
        # 使用 'updates' 模式可以获取节点级别的更新，用于进度跟踪
        # 使用 'values' 模式可以获取完整的状态更新
        stream_mode = "updates" if use_progress_callback else "values"

        return {
            "stream_mode": stream_mode,
            "config": {"recursion_limit": self.max_recur_limit},
        }
