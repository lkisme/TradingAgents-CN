#!/usr/bin/env python3
"""
创建 MongoDB cache_metadata 集合和索引 - 简化版本
直接使用 pymongo，不依赖项目其他模块
"""
import pymongo
from pymongo import MongoClient
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_cache_metadata():
    """创建 cache_metadata 集合和索引"""
    
    # 从环境变量读取 MongoDB 配置
    mongodb_host = os.getenv('MONGODB_HOST', 'localhost')
    mongodb_port = int(os.getenv('MONGODB_PORT', '27017'))
    mongodb_database = os.getenv('MONGODB_DATABASE', 'tradingagents')
    mongodb_username = os.getenv('MONGODB_USERNAME')
    mongodb_password = os.getenv('MONGODB_PASSWORD')
    mongodb_auth_source = os.getenv('MONGODB_AUTH_SOURCE', 'admin')
    
    logger.info(f"📊 MongoDB 配置: {mongodb_host}:{mongodb_port}/{mongodb_database}")
    
    try:
        # 构建连接参数
        connect_kwargs = {
            'host': mongodb_host,
            'port': mongodb_port,
            'serverSelectionTimeoutMS': 5000
        }
        
        # 如果有认证信息，添加认证
        if mongodb_username and mongodb_password:
            connect_kwargs.update({
                'username': mongodb_username,
                'password': mongodb_password,
                'authSource': mongodb_auth_source
            })
        
        # 连接 MongoDB
        client = MongoClient(**connect_kwargs)
        db = client[mongodb_database]
        
        # 测试连接
        client.server_info()
        logger.info("✅ MongoDB 连接成功")
        
        # 1. 创建集合（如果不存在）
        collections = db.list_collection_names()
        if 'cache_metadata' not in collections:
            db.create_collection("cache_metadata")
            logger.info("✅ cache_metadata 集合已创建")
        else:
            logger.info("ℹ️ cache_metadata 集合已存在")
        
        # 2. 创建索引
        existing_indexes = db.cache_metadata.index_information()
        
        # 索引1: symbol + collection（唯一索引）
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
        if 'stock_daily_quotes' in collections:
            existing_quotes_indexes = db.stock_daily_quotes.index_information()
            
            # 索引1: symbol + trade_date（复合索引）
            if 'symbol_1_trade_date_-1' not in existing_quotes_indexes:
                db.stock_daily_quotes.create_index(
                    [('symbol', 1), ('trade_date', -1)],
                    name='symbol_1_trade_date_-1'
                )
                logger.info("✅ stock_daily_quotes 索引已创建: symbol + trade_date")
            else:
                logger.info("ℹ️ stock_daily_quotes 紙引已存在: symbol + trade_date")
            
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
    success = create_cache_metadata()
    exit(0 if success else 1)