#!/usr/bin/env python3
"""
创建 MongoDB cache_metadata 集合和索引
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, '/root/workspace/TradingAgents-CN')

from tradingagents.config.database_manager import get_database_manager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_cache_metadata_collection():
    """创建 cache_metadata 集合和索引"""
    
    # 获取数据库管理器
    db_manager = get_database_manager()
    
    if not db_manager.is_mongodb_available():
        logger.error("❌ MongoDB 不可用，无法创建集合")
        return False
    
    try:
        # 获取 MongoDB 客户端
        client = db_manager.get_mongodb_client()
        db_name = db_manager.mongodb_config.get('database', 'tradingagents')
        db = client[db_name]
        
        logger.info(f"📊 连接到 MongoDB: {db_name}")
        
        # 1. 创建集合（如果不存在）
        if 'cache_metadata' not in db.list_collection_names():
            db.create_collection("cache_metadata")
            logger.info("✅ cache_metadata 集合已创建")
        else:
            logger.info("ℹ️ cache_metadata 集合已存在")
        
        # 2. 创建索引
        # 索引1: symbol + collection（唯一索引）
        existing_indexes = db.cache_metadata.index_information()
        
        if 'symbol_1_collection_1' not in existing_indexes:
            db.cache_metadata.create_index(
                [('symbol', 1), ('collection', 1)],
                unique=True,
                name='symbol_1_collection_1'
            )
            logger.info("✅ 索引已创建: symbol + collection (唯一)")
        else:
            logger.info("ℹ️ 索引已存在: symbol + collection")
        
        # 索引2: last_sync_date
        if 'last_sync_date_1' not in existing_indexes:
            db.cache_metadata.create_index(
                [('last_sync_date', 1)],
                name='last_sync_date_1'
            )
            logger.info("✅ 索引已创建: last_sync_date")
        else:
            logger.info("ℹ️ 索引已存在: last_sync_date")
        
        # 3. 优化 stock_daily_quotes 索引（如果需要）
        if 'stock_daily_quotes' in db.list_collection_names():
            existing_quotes_indexes = db.stock_daily_quotes.index_information()
            
            # 索引1: symbol + trade_date（复合索引）
            if 'symbol_1_trade_date_-1' not in existing_quotes_indexes:
                db.stock_daily_quotes.create_index(
                    [('symbol', 1), ('trade_date', -1)],
                    name='symbol_1_trade_date_-1'
                )
                logger.info("✅ stock_daily_quotes 索引已创建: symbol + trade_date")
            else:
                logger.info("ℹ️ stock_daily_quotes 索引已存在: symbol + trade_date")
            
            # 索引2: trade_date（单字段索引）
            if 'trade_date_-1' not in existing_quotes_indexes:
                db.stock_daily_quotes.create_index(
                    [('trade_date', -1)],
                    name='trade_date_-1'
                )
                logger.info("✅ stock_daily_quotes 索引已创建: trade_date")
            else:
                logger.info("ℹ️ stock_daily_quotes 索引已存在: trade_date")
        
        logger.info("✅ MongoDB 集合和索引创建完成")
        return True
        
    except Exception as e:
        logger.error(f"❌ 创建集合和索引失败: {e}", exc_info=True)
        return False


if __name__ == '__main__':
    success = create_cache_metadata_collection()
    sys.exit(0 if success else 1)