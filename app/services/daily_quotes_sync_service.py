#!/usr/bin/env python3
"""
Daily Quotes Sync Service
日线行情定时同步服务
"""
from datetime import datetime
from typing import List, Dict
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class DailyQuotesSyncService:
    """日线行情定时同步服务"""
    
    def __init__(self):
        self._cache_adapter = None
        self._akshare_provider = None
    
    def _get_cache_adapter(self):
        """获取缓存适配器"""
        if self._cache_adapter is None:
            from tradingagents.dataflows.cache.enhanced_mongodb_adapter import EnhancedMongoDBCacheAdapter
            self._cache_adapter = EnhancedMongoDBCacheAdapter()
        return self._cache_adapter
    
    def _get_akshare_provider(self):
        """获取 AKShare Provider"""
        if self._akshare_provider is None:
            from tradingagents.dataflows.providers.china.akshare import get_akshare_provider
            self._akshare_provider = get_akshare_provider()
        return self._akshare_provider
    
    async def sync_stock_pool(self, stock_pool: List[str]) -> Dict:
        """
        同步股票池的日线数据
        
        Args:
            stock_pool: 股票代码列表
        
        Returns:
            {'success': int, 'failed': int, 'skipped': int, 'errors': list}
        """
        
        from tradingagents.utils.trading_day_utils import TradingDayUtils
        
        results = {'success': 0, 'failed': 0, 'skipped': 0, 'errors': []}
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 检查是否收盘后
        if not TradingDayUtils.is_after_market_close():
            logger.warning("⚠️ 非收盘后时段，跳过同步")
            return results
        
        adapter = self._get_cache_adapter()
        akshare = self._get_akshare_provider()
        
        # 计算同步范围（一年交易日）
        one_year_ago = TradingDayUtils.get_one_year_ago_trading_day()
        latest_closed = TradingDayUtils.get_latest_closed_trading_day()
        
        logger.info(f"📊 开始同步 {len(stock_pool)} 只股票，范围: {one_year_ago} ~ {latest_closed}")
        
        for i, symbol in enumerate(stock_pool):
            try:
                # 每 50 只打印进度
                if i % 50 == 0:
                    logger.info(f"进度: [{i}/{len(stock_pool)}]")
                
                # 检查是否已同步（跳过当天已同步的）
                metadata = adapter.get_cache_metadata(symbol)
                if metadata and metadata.get('last_sync_date') == today:
                    results['skipped'] += 1
                    continue
                
                # 检查缓存是否完整（跳过已完整的）
                is_complete, reason, _ = adapter.validate_cache_by_date_range(symbol)
                if is_complete:
                    results['skipped'] += 1
                    logger.debug(f"⏭️ [{symbol}] 缓存完整，跳过")
                    continue
                
                # 确定获取策略
                strategy, fetch_start, fetch_end = adapter.get_fetch_strategy(symbol, metadata)
                
                if strategy == 'skip':
                    results['skipped'] += 1
                    continue
                
                # 获取数据
                data = await akshare.get_historical_data(symbol, fetch_start, fetch_end)
                
                if data and not data.empty:
                    # 写入 MongoDB
                    adapter.save_historical_data_bulk(symbol, data, 'akshare')
                    
                    # 更新元数据
                    earliest = data['trade_date'].min()
                    latest = data['trade_date'].max()
                    is_complete = earliest <= one_year_ago and latest >= latest_closed
                    
                    adapter.update_cache_metadata(
                        symbol=symbol,
                        earliest_date=earliest,
                        latest_date=latest,
                        total_records=len(data),
                        is_complete=is_complete,
                        data_source='akshare'
                    )
                    
                    results['success'] += 1
                    logger.info(f"✅ [{symbol}] 同步成功，{len(data)} 条")
                else:
                    results['failed'] += 1
                    results['errors'].append(f"{symbol}: 无数据")
                    logger.warning(f"⚠️ [{symbol}] 无数据")
                
                # 每 20 只休息一下（避免 API 过载）
                if (i + 1) % 20 == 0:
                    import asyncio
                    await asyncio.sleep(1)
                
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f"{symbol}: {str(e)[:50]}")
                logger.error(f"❌ [{symbol}] 同步失败: {str(e)[:50]}")
        
        logger.info(f"📊 同步完成: 成功={results['success']}, 失败={results['failed']}, 跳过={results['skipped']}")
        
        # 失败超过 10% → 发送通知
        if results['failed'] > len(stock_pool) * 0.1:
            logger.warning(f"⚠️ 日线同步失败率 {results['failed']}/{len(stock_pool)}")
        
        return results


# 全局实例
_daily_quotes_sync_service = None


def get_daily_quotes_sync_service() -> DailyQuotesSyncService:
    """获取日线同步服务实例"""
    global _daily_quotes_sync_service
    if _daily_quotes_sync_service is None:
        _daily_quotes_sync_service = DailyQuotesSyncService()
    return _daily_quotes_sync_service
