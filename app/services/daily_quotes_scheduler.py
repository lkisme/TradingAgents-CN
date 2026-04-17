#!/usr/bin/env python3
"""
Daily Quotes Scheduler
日线数据同步定时任务
"""
import logging
from typing import Dict

logger = logging.getLogger(__name__)


async def job_sync_daily_quotes() -> Dict:
    """
    每日收盘后同步日线数据
    
    定时任务：16:30 执行
    """
    
    from app.services.daily_quotes_sync_service import get_daily_quotes_sync_service
    from app.services.stock_pool_service import get_stock_pool_for_sync
    
    logger.info("=" * 60)
    logger.info("🔄 每日日线数据同步任务启动")
    logger.info("=" * 60)
    
    try:
        # 获取股票池
        stock_pool = await get_stock_pool_for_sync()
        
        if not stock_pool:
            logger.warning("⚠️ 股票池为空，跳过同步")
            return {'status': 'skipped', 'reason': 'empty_pool'}
        
        logger.info(f"📊 股票池: {len(stock_pool)} 只")
        
        # 同步
        sync_service = get_daily_quotes_sync_service()
        results = await sync_service.sync_stock_pool(stock_pool)
        
        logger.info(f"✅ 同步完成: {results}")
        
        return {
            'status': 'success',
            'stock_pool_size': len(stock_pool),
            'results': results
        }
        
    except Exception as e:
        logger.error(f"❌ 同步任务失败: {e}")
        return {'status': 'failed', 'error': str(e)}
