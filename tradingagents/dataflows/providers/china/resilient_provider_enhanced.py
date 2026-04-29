#!/usr/bin/env python3
"""
Resilient China Stock Provider Enhanced
增强版 Resilient Provider（MongoDB 缓存优先，日期范围验证）
"""
from datetime import datetime
import pandas as pd
import logging
from typing import Optional

from tradingagents.dataflows.cache.enhanced_mongodb_adapter import EnhancedMongoDBCacheAdapter
from tradingagents.utils.trading_day_utils import TradingDayUtils

logger = logging.getLogger(__name__)


class ResilientChinaStockProviderEnhanced:
    """增强版 Resilient Provider（MongoDB 缓存优先，日期范围验证）"""
    
    def __init__(self):
        self._akshare_provider = None
        self._baostock_provider = None
        self._cache_adapter = None
        self._current_source = None
    
    def _get_akshare_provider(self):
        """获取 AKShare Provider"""
        if self._akshare_provider is None:
            from .akshare import get_akshare_provider
            self._akshare_provider = get_akshare_provider()
        return self._akshare_provider
    
    def _get_baostock_provider(self):
        """获取 BaoStock Provider"""
        if self._baostock_provider is None:
            from .baostock import get_baostock_provider
            self._baostock_provider = get_baostock_provider()
        return self._baostock_provider
    
    def _get_cache_adapter(self):
        """获取缓存适配器"""
        if self._cache_adapter is None:
            self._cache_adapter = EnhancedMongoDBCacheAdapter()
        return self._cache_adapter
    
    async def get_historical_data(
        self,
        symbol: str,
        start_date: str = None,
        end_date: str = None,
        period: str = "daily"
    ) -> pd.DataFrame:
        """
        获取历史数据（MongoDB 缓存优先）
        
        优先级：
        1. MongoDB 缓存（日期范围验证）
        2. AKShare API（失败重试）
        3. BaoStock API（备用）
        4. 全失败 → 抛出 DataFetchError，终止分析
        
        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            period: 周期
        
        Returns:
            DataFrame: 历史数据
        """
        
        adapter = self._get_cache_adapter()
        
        # === 第一优先级：验证缓存完整性 ===
        logger.info(f"📊 [MongoDB优先] 检查缓存: {symbol}")
        
        is_complete, reason, stats = adapter.validate_cache_by_date_range(symbol)
        
        if is_complete:
            # 缓存完整 -> 直接返回
            earliest = stats['earliest_date']
            latest = stats['latest_date']
            cached_data = adapter.query_historical_data(symbol, earliest, latest)
            if not cached_data.empty:
                logger.info(f"✅ [{symbol}] 缓存命中且完整({earliest}~{latest})，返回 {len(cached_data)} 条")
                self._current_source = 'mongodb_cache'
                return cached_data
        
        # === 缓存不完整 -> 确定获取策略 ===
        logger.warning(f"⚠️ [{symbol}] 缓存不完整: {reason}")
        strategy, fetch_start, fetch_end = adapter.get_fetch_strategy(symbol, stats)
        
        if strategy == 'skip':
            logger.info(f"⏭️ [{symbol}] 获取策略=skip，无数据")
            raise DataFetchError(f"{symbol} 无可用数据")
        
        # === 获取现有缓存数据（用于合并）===
        existing_data = None
        if stats and stats.get('earliest_date'):
            existing_data = adapter.query_historical_data(
                symbol, stats['earliest_date'], stats['latest_date']
            )
        
        # === 第二优先级：AKShare API ===
        logger.info(f"🔄 [AKShare] 尝试获取: {symbol} ({fetch_start} ~ {fetch_end})")
        
        try:
            akshare = self._get_akshare_provider()
            data = await akshare.get_historical_data(symbol, fetch_start, fetch_end)
            
            if data is not None and not data.empty:
                logger.info(f"✅ [AKShare] 获取成功: {symbol}, {len(data)} 条")
                # 写入缓存
                adapter.save_historical_data_bulk(symbol, data, 'akshare')
                # 🔥 不再维护 metadata
                self._current_source = 'akshare'
                # 合并数据（增量场景）
                if existing_data and strategy in ['incremental', 'gap']:
                    data = self._merge_data(existing_data, data)
                return data
        
        except Exception as e:
            logger.warning(f"⚠️ [AKShare] 获取失败: {e}")
        
        # === 第三优先级：BaoStock API ===
        logger.info(f"🔄 [BaoStock] 尝试获取: {symbol}")
        
        try:
            baostock = self._get_baostock_provider()
            data = await baostock.get_historical_data(symbol, fetch_start, fetch_end)
            
            if data is not None and not data.empty:
                logger.info(f"✅ [BaoStock] 获取成功: {symbol}, {len(data)} 条")
                # 写入缓存
                adapter.save_historical_data_bulk(symbol, data, 'baostock')
                # 🔥 不再维护 metadata
                self._current_source = 'baostock'
                # 合并数据
                if existing_data and strategy in ['incremental', 'gap']:
                    data = self._merge_data(existing_data, data)
                return data
        
        except Exception as e:
            logger.error(f"❌ [BaoStock] 获取失败: {e}")
        
        # === 全失败 → 抛出异常，终止分析 ===
        error_msg = f"无法获取 {symbol} 的日线数据（MongoDB缓存不完整 + AKShare/BaoStock API全失败）"
        logger.error(f"❌ {error_msg}")
        raise DataFetchError(error_msg)
    
    # 🔥 _update_metadata 方法已删除，不再维护 metadata
    
    def _merge_data(self, existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        """
        合并数据（去重）
        
        Args:
            existing: 现有数据
            new: 新数据
        
        Returns:
            DataFrame: 合并后的数据
        """
        # ✅ 统一日期字段名（BaoStock 用 'date', AKShare 用 'trade_date'）
        if 'date' in new.columns and 'trade_date' not in new.columns:
            new = new.rename(columns={'date': 'trade_date'})
        if 'date' in existing.columns and 'trade_date' not in existing.columns:
            existing = existing.rename(columns={'date': 'trade_date'})
        
        merged = pd.concat([existing, new])
        merged = merged.drop_duplicates(subset=['trade_date'], keep='last')
        merged = merged.sort_values('trade_date')
        return merged
    
    def get_current_source(self) -> str:
        """获取当前数据源"""
        return self._current_source


class DataFetchError(Exception):
    """数据获取失败异常"""
    pass


# 全局实例
_enhanced_resilient_provider = None


def get_enhanced_resilient_provider() -> ResilientChinaStockProviderEnhanced:
    """获取增强版 Resilient Provider"""
    global _enhanced_resilient_provider
    if _enhanced_resilient_provider is None:
        _enhanced_resilient_provider = ResilientChinaStockProviderEnhanced()
    return _enhanced_resilient_provider