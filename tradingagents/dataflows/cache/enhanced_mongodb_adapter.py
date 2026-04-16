#!/usr/bin/env python3
"""
Enhanced MongoDB Cache Adapter
增强版 MongoDB 缓存适配器（支持日期范围验证）
"""
from datetime import datetime
from typing import Tuple, Optional
import pandas as pd
import pymongo
import logging

from tradingagents.utils.trading_day_utils import TradingDayUtils

logger = logging.getLogger(__name__)


class EnhancedMongoDBCacheAdapter:
    """增强版 MongoDB 缓存适配器（支持日期范围验证）"""
    
    def __init__(self, db_client=None):
        self._db_client = db_client
    
    def _get_db(self):
        """获取 MongoDB 数据库实例"""
        if self._db_client is None:
            from tradingagents.config.database_manager import get_database_manager
            db_manager = get_database_manager()
            self._db_client = db_manager.get_mongodb_client()
        
        if self._db_client is None:
            raise RuntimeError("MongoDB客户端不可用")
        
        return self._db_client['tradingagents']
    
    def validate_cache_by_date_range(self, symbol: str) -> Tuple[bool, str, Optional[dict]]:
        """
        用日期范围验证缓存完整性
        
        Args:
            symbol: 股票代码
        
        Returns:
            (is_complete, reason, metadata): 完整性标记、原因、元数据
        """
        
        metadata = self.get_cache_metadata(symbol)
        
        if not metadata:
            return False, "无缓存元数据", None
        
        earliest_date = metadata.get('earliest_date')
        latest_date = metadata.get('latest_date')
        
        if not earliest_date or not latest_date:
            return False, "缺少日期范围", metadata
        
        # === 计算判断基准 ===
        one_year_ago = TradingDayUtils.get_one_year_ago_trading_day()
        latest_closed_day = TradingDayUtils.get_latest_closed_trading_day()
        
        # === 判断完整性 ===
        earliest_valid = earliest_date <= one_year_ago
        latest_valid = latest_date >= latest_closed_day
        
        if earliest_valid and latest_valid:
            logger.info(f"✅ [{symbol}] 缓存完整: "
                       f"earliest={earliest_date} ≤ {one_year_ago}, "
                       f"latest={latest_date} ≥ {latest_closed_day}")
            return True, "缓存完整", metadata
        
        # === 分析不完整原因 ===
        reasons = []
        
        if not earliest_valid:
            reasons.append(f"起始不足（{earliest_date} > {one_year_ago}）")
        
        if not latest_valid:
            gap_days = (datetime.strptime(latest_closed_day, '%Y-%m-%d') - 
                       datetime.strptime(latest_date, '%Y-%m-%d')).days
            reasons.append(f"有Gap（{gap_days}天，{latest_date} → {latest_closed_day}）")
        
        reason = ", ".join(reasons)
        logger.warning(f"⚠️ [{symbol}] 缓存不完整: {reason}")
        
        return False, reason, metadata
    
    def get_cache_metadata(self, symbol: str) -> Optional[dict]:
        """
        获取缓存元数据
        
        Args:
            symbol: 股票代码
        
        Returns:
            dict: 缓存元数据，如果没有则返回None
        """
        try:
            db = self._get_db()
            return db.cache_metadata.find_one({
                'symbol': symbol,
                'collection': 'stock_daily_quotes'
            })
        except Exception as e:
            logger.error(f"获取缓存元数据失败: {e}")
            return None
    
    def update_cache_metadata(
        self,
        symbol: str,
        earliest_date: str,
        latest_date: str,
        total_records: int,
        is_complete: bool,
        data_source: str = 'akshare'
    ):
        """
        更新缓存元数据
        
        Args:
            symbol: 股票代码
            earliest_date: 最早日期
            latest_date: 最晚日期
            total_records: 总记录数
            is_complete: 是否完整
            data_source: 数据源
        """
        try:
            db = self._get_db()
            db.cache_metadata.update_one(
                {'symbol': symbol, 'collection': 'stock_daily_quotes'},
                {
                    '$set': {
                        'symbol': symbol,
                        'collection': 'stock_daily_quotes',
                        'earliest_date': earliest_date,
                        'latest_date': latest_date,
                        'total_records': total_records,
                        'is_complete': is_complete,
                        'last_sync_date': datetime.now().strftime('%Y-%m-%d'),
                        'data_source': data_source,
                        'updated_at': datetime.now()
                    }
                },
                upsert=True
            )
            logger.info(f"✅ [{symbol}] 元数据已更新: {earliest_date} ~ {latest_date}, {total_records}条")
        except Exception as e:
            logger.error(f"更新缓存元数据失败: {e}")
    
    def query_historical_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        查询历史数据
        
        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataFrame: 历史数据
        """
        try:
            db = self._get_db()
            
            cursor = db.stock_daily_quotes.find({
                'symbol': symbol,
                'trade_date': {'$gte': start_date, '$lte': end_date}
            }).sort('trade_date', 1)
            
            data = list(cursor)
            if not data:
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            df['trade_date'] = df['trade_date'].astype(str)
            return df
        except Exception as e:
            logger.error(f"查询历史数据失败: {e}")
            return pd.DataFrame()
    
    def save_historical_data_bulk(self, symbol: str, data: pd.DataFrame, data_source: str = 'akshare'):
        """
        批量写入历史数据（upsert 模式）
        
        Args:
            symbol: 股票代码
            data: 历史数据 DataFrame
            data_source: 数据源
        """
        if data.empty:
            logger.warning(f"[{symbol}] 数据为空，跳过写入")
            return
        
        try:
            db = self._get_db()
            bulk_ops = []
            
            for _, row in data.iterrows():
                trade_date = str(row.get('date', row.get('trade_date', '')))
                if not trade_date:
                    continue
                
                bulk_ops.append(pymongo.UpdateOne(
                    {'symbol': symbol, 'trade_date': trade_date},
                    {
                        '$set': {
                            'symbol': symbol,
                            'code': symbol,
                            'full_symbol': f"{symbol}.SH" if symbol.startswith('6') else f"{symbol}.SZ",
                            'market': 'CN',
                            'trade_date': trade_date,
                            'period': 'daily',
                            'open': float(row.get('open', 0)),
                            'high': float(row.get('high', 0)),
                            'low': float(row.get('low', 0)),
                            'close': float(row.get('close', 0)),
                            'volume': int(row.get('volume', row.get('vol', 0))),
                            'amount': float(row.get('amount', 0)),
                            'pct_chg': float(row.get('pct_chg', row.get('change_percent', 0))),
                            'data_source': data_source,
                            'updated_at': datetime.now()
                        }
                    },
                    upsert=True
                ))
            
            if bulk_ops:
                result = db.stock_daily_quotes.bulk_write(bulk_ops)
                logger.info(f"✅ [{symbol}] 写入 {result.upserted_count} 条日线数据")
        except Exception as e:
            logger.error(f"批量写入历史数据失败: {e}")
    
    def get_fetch_strategy(self, symbol: str, metadata: Optional[dict]) -> Tuple[str, str, str]:
        """
        确定数据获取策略
        
        Args:
            symbol: 股票代码
            metadata: 缓存元数据
        
        Returns:
            (strategy, fetch_start, fetch_end): 
            - strategy: 'skip', 'full', 'incremental', 'gap'
            - fetch_start, fetch_end: 需要获取的日期范围
        """
        
        one_year_ago = TradingDayUtils.get_one_year_ago_trading_day()
        latest_closed_day = TradingDayUtils.get_latest_closed_trading_day()
        
        # 无缓存 → 全量获取
        if not metadata:
            logger.info(f"🔄 [{symbol}] 无缓存，全量获取")
            return 'full', one_year_ago, latest_closed_day
        
        earliest_date = metadata.get('earliest_date')
        latest_date = metadata.get('latest_date')
        
        if not earliest_date or not latest_date:
            logger.info(f"🔄 [{symbol}] 元数据不完整，全量获取")
            return 'full', one_year_ago, latest_closed_day
        
        # 起始不足 → 全量获取
        if earliest_date > one_year_ago:
            logger.info(f"🔄 [{symbol}] 起始不足（{earliest_date} > {one_year_ago}），全量获取")
            return 'full', one_year_ago, latest_closed_day
        
        # 盘中 → 不补当日
        if TradingDayUtils._is_trading_time(datetime.now()):
            yesterday = TradingDayUtils.get_yesterday_trading_day()
            if latest_date >= yesterday:
                logger.info(f"✅ [{symbol}] 盘中缓存有效（latest={latest_date} ≥ yesterday={yesterday}），跳过")
                return 'skip', '', ''
            else:
                # 盘中有 Gap，但只补到昨日（不补当日）
                gap_end = yesterday
                logger.info(f"🔄 [{symbol}] 盘中有Gap，补到昨日（{latest_date} → {gap_end}）")
                return 'gap', latest_date, gap_end
        
        # 收盘后 → 检查 Gap
        if latest_date < latest_closed_day:
            gap_days = (datetime.strptime(latest_closed_day, '%Y-%m-%d') - 
                       datetime.strptime(latest_date, '%Y-%m-%d')).days
            
            if gap_days > 7:
                # Gap > 7 天 → 全量获取
                logger.info(f"🔄 [{symbol}] Gap {gap_days}天 > 7，全量获取")
                return 'full', one_year_ago, latest_closed_day
            else:
                # Gap ≤ 7 天 → 增量补
                logger.info(f"🔄 [{symbol}] Gap {gap_days}天 ≤ 7，增量补")
                return 'incremental', latest_date, latest_closed_day
        
        # 缓存完整 → 跳过
        logger.info(f"✅ [{symbol}] 缓存完整，跳过")
        return 'skip', '', ''


# 全局实例
_enhanced_mongodb_adapter = None


def get_enhanced_mongodb_adapter() -> EnhancedMongoDBCacheAdapter:
    """获取全局 EnhancedMongoDBCacheAdapter 实例"""
    global _enhanced_mongodb_adapter
    if _enhanced_mongodb_adapter is None:
        _enhanced_mongodb_adapter = EnhancedMongoDBCacheAdapter()
    return _enhanced_mongodb_adapter