#!/usr/bin/env python3
"""
Stock Pool Service
股票池获取服务
"""
from typing import List
import logging

logger = logging.getLogger(__name__)


async def get_stock_pool_for_sync() -> List[str]:
    """
    获取需要同步日线数据的股票池
    
    Returns:
        List[str]: 股票代码列表（Top 120 + 当前持仓）
    """
    
    from tradingagents.config.database_manager import get_database_manager
    
    db_manager = get_database_manager()
    mongodb_client = db_manager.get_mongodb_client()
    
    if mongodb_client is None:
        logger.error("MongoDB 客户端不可用")
        return []
    
    db = mongodb_client['tradingagents']
    
    stocks = set()
    
    # 1. 从 cache_metadata 获取所有已缓存的股票（Top 120）
    cache_stocks = db.cache_metadata.find({'collection': 'stock_daily_quotes'})
    for doc in cache_stocks:
        if doc.get('symbol'):
            stocks.add(doc['symbol'])
    
    logger.info(f"📊 从缓存元数据获取 {len(stocks)} 只股票")
    
    # 2. 从 stock_basic_info 获取（如果有）
    basic_stocks = db.stock_basic_info.find({}).limit(200)
    for doc in basic_stocks:
        if doc.get('symbol'):
            stocks.add(doc['symbol'])
    
    logger.info(f"📊 合并后股票池: {len(stocks)} 只")
    
    return list(stocks)


async def get_top_120_stocks() -> List[str]:
    """
    获取 Top 120 股票池
    
    Returns:
        List[str]: Top 120 股票代码列表
    """
    
    from tradingagents.config.database_manager import get_database_manager
    
    db_manager = get_database_manager()
    mongodb_client = db_manager.get_mongodb_client()
    
    if mongodb_client is None:
        return []
    
    db = mongodb_client['tradingagents']
    
    # 从缓存获取有数据的股票
    stocks = []
    cursor = db.cache_metadata.find({
        'collection': 'stock_daily_quotes',
        'is_complete': True
    }).limit(120)
    
    for doc in cursor:
        if doc.get('symbol'):
            stocks.append(doc['symbol'])
    
    return stocks
