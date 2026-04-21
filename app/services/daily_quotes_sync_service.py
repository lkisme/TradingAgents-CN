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
        self._baostock_provider = None
    
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
    
    def _get_baostock_provider(self):
        """获取 BaoStock Provider（备用）"""
        if self._baostock_provider is None:
            from tradingagents.dataflows.providers.china.baostock import get_baostock_provider
            self._baostock_provider = get_baostock_provider()
        return self._baostock_provider
    
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
        baostock = self._get_baostock_provider()
        
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
                
                # 获取数据（AKShare 优先，BaoStock 降级）
                data = None
                data_source = None
                
                # 尝试 AKShare
                try:
                    data = await akshare.get_historical_data(symbol, fetch_start, fetch_end)
                    if data is not None and not data.empty:
                        data_source = 'akshare'
                        logger.debug(f"✅ [{symbol}] AKShare 获取成功")
                    else:
                        data = None  # 清空无效数据
                except Exception as ak_err:
                    logger.warning(f"⚠️ [{symbol}] AKShare 失败: {str(ak_err)[:30]}，尝试 BaoStock")
                    data = None
                
                # AKShare 失败 → 尝试 BaoStock
                if data is None:
                    try:
                        data = await baostock.get_historical_data(symbol, fetch_start, fetch_end)
                        if data is not None and not data.empty:
                            data_source = 'baostock'
                            logger.info(f"✅ [{symbol}] BaoStock 降级成功")
                        else:
                            data = None
                    except Exception as bs_err:
                        logger.error(f"❌ [{symbol}] BaoStock 也失败: {str(bs_err)[:30]}")
                        data = None
                
                if data is not None and not data.empty:
                    # 写入 MongoDB
                    adapter.save_historical_data_bulk(symbol, data, data_source)
                    
                    # ✅ 从数据库统计实际数据（包括历史数据）
                    actual_stats = adapter.get_historical_data_stats(symbol)
                    
                    # 计算完整性（使用实际统计）
                    actual_earliest = actual_stats.get('earliest_date')
                    actual_latest = actual_stats.get('latest_date')
                    actual_total = actual_stats.get('total_records', 0)
                    
                    is_complete = (
                        actual_earliest and actual_latest and 
                        str(actual_earliest) <= str(one_year_ago) and 
                        str(actual_latest) >= str(latest_closed)
                    )
                    
                    # 更新元数据（使用实际统计）
                    adapter.update_cache_metadata(
                        symbol=symbol,
                        earliest_date=actual_earliest,
                        latest_date=actual_latest,
                        total_records=actual_total,
                        is_complete=is_complete,
                        data_source=data_source  # ← 使用本次同步的数据源
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
