#!/usr/bin/env python3
"""
Stock Pool Service
股票池获取服务

股票池来源：
- Top120 股票（stock_data.selected_pool, is_top_120=true）
- 当前持仓股票（tradingagents.paper_positions, quantity > 0）
"""
from typing import List, Set
import logging

logger = logging.getLogger(__name__)


def normalize_symbol(symbol: str) -> str:
    """
    统一股票代码格式
    
    输入格式：
    - "SZ000030" / "SH600036"（带市场前缀）
    - "000030" / "600036"（无前缀）
    
    输出格式：
    - "000030" / "600036"（无前缀，6位代码）
    
    Args:
        symbol: 原始股票代码
        
    Returns:
        str: 统一后的股票代码（6位）
    """
    if not symbol:
        return ""
    
    # 去掉市场前缀
    if symbol.startswith("SH") or symbol.startswith("SZ"):
        return symbol[2:]
    
    # 已经是统一格式
    return symbol


async def get_stock_pool_for_sync() -> List[str]:
    """
    获取需要同步日线数据的股票池
    
    数据来源：
    1. Top120 股票（stock_data.selected_pool）
    2. 当前持仓股票（tradingagents.paper_positions）
    
    Returns:
        List[str]: 股票代码列表（Top 120 + 当前持仓，去重）
    """
    
    from tradingagents.config.database_manager import get_database_manager
    
    db_manager = get_database_manager()
    mongodb_client = db_manager.get_mongodb_client()
    
    if mongodb_client is None:
        logger.error("MongoDB 客户端不可用")
        return []
    
    stocks: Set[str] = set()
    
    try:
        # 1. 获取 Top120 股票（跨库访问 stock_data）
        db_stock_data = mongodb_client['stock_data']
        cursor = db_stock_data.selected_pool.find({'is_top_120': True})
        
        top120_count = 0
        for doc in cursor:
            symbol = doc.get('symbol')
            if symbol:
                normalized = normalize_symbol(symbol)
                if normalized:
                    stocks.add(normalized)
                    top120_count += 1
        
        logger.info(f"📊 从 Top120 获取 {top120_count} 只股票")
        
        # 2. 获取所有用户的持仓股票
        db_tradingagents = mongodb_client['tradingagents']
        cursor = db_tradingagents.paper_positions.find({'quantity': {'$gt': 0}})
        
        position_count = 0
        for doc in cursor:
            code = doc.get('code')
            if code:
                normalized = normalize_symbol(code)
                if normalized:
                    stocks.add(normalized)
                    position_count += 1
        
        logger.info(f"📊 从持仓获取 {position_count} 只股票")
        
        # 3. 合并去重后的总数
        logger.info(f"📊 合并后股票池: {len(stocks)} 只")
        
        if len(stocks) == 0:
            logger.warning("⚠️ 股票池为空，请检查 Top120 和持仓数据")
        
        return list(stocks)
        
    except Exception as e:
        logger.error(f"❌ 获取股票池失败: {e}")
        return []


async def get_top_120_stocks() -> List[str]:
    """
    获取 Top 120 股票池（从 stock_data.selected_pool）
    
    Returns:
        List[str]: Top 120 股票代码列表
    """
    
    from tradingagents.config.database_manager import get_database_manager
    
    db_manager = get_database_manager()
    mongodb_client = db_manager.get_mongodb_client()
    
    if mongodb_client is None:
        return []
    
    try:
        db_stock_data = mongodb_client['stock_data']
        
        stocks = []
        cursor = db_stock_data.selected_pool.find({'is_top_120': True})
        
        for doc in cursor:
            symbol = doc.get('symbol')
            if symbol:
                normalized = normalize_symbol(symbol)
                if normalized:
                    stocks.append(normalized)
        
        logger.info(f"📊 Top120 股票: {len(stocks)} 只")
        return stocks
        
    except Exception as e:
        logger.error(f"❌ 获取 Top120 失败: {e}")
        return []


async def get_position_stocks() -> List[str]:
    """
    获取当前持仓股票池（从 tradingagents.paper_positions）
    
    Returns:
        List[str]: 持仓股票代码列表
    """
    
    from tradingagents.config.database_manager import get_database_manager
    
    db_manager = get_database_manager()
    mongodb_client = db_manager.get_mongodb_client()
    
    if mongodb_client is None:
        return []
    
    try:
        db_tradingagents = mongodb_client['tradingagents']
        
        stocks = []
        cursor = db_tradingagents.paper_positions.find({'quantity': {'$gt': 0}})
        
        for doc in cursor:
            code = doc.get('code')
            if code:
                normalized = normalize_symbol(code)
                if normalized:
                    stocks.append(normalized)
        
        logger.info(f"📊 持仓股票: {len(stocks)} 只")
        return stocks
        
    except Exception as e:
        logger.error(f"❌ 获取持仓失败: {e}")
        return []