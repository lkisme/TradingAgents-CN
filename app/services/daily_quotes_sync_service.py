#!/usr/bin/env python3
"""
Daily Quotes Sync Service
日线行情定时同步服务

🔥 改进策略：使用实时行情 API 补充当天日线数据
- Gap <= 1 天 → 实时行情 API（更稳定）
- Gap > 1 天 → 跳过，记录需要手动补充
"""
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
import pandas as pd
import logging
import asyncio
import random
import requests

logger = logging.getLogger(__name__)


class DailyQuotesSyncService:
    """日线行情定时同步服务"""
    
    def __init__(self):
        self._cache_adapter = None
        self._akshare_provider = None
        self._baostock_provider = None
        # 重试配置
        self.max_retries = 3  # 最大重试次数
        self.retry_base_delay = 1.0  # 基础延迟（秒）
        self.request_interval = 0.3  # 每次请求间隔（秒）
        # 需要手动补充历史数据的股票列表
        self.need_manual_sync: List[str] = []
    
    async def _retry_with_backoff(self, coro, max_retries: int = 3) -> tuple:
        """
        指数退避重试机制
        
        Args:
            coro: 要执行的协程
            max_retries: 最大重试次数
        
        Returns:
            (success: bool, result_or_error: any)
        """
        for attempt in range(max_retries):
            try:
                result = await coro
                return (True, result)
            except Exception as e:
                if attempt < max_retries - 1:
                    # 指数退避 + 随机抖动
                    delay = self.retry_base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(f"⚠️ 重试 {attempt + 1}/{max_retries}, 等待 {delay:.1f}s: {str(e)[:30]}")
                    await asyncio.sleep(delay)
                else:
                    return (False, str(e))
        return (False, "Unknown error")
    
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
    
    async def fix_sina_kline_amount(self, stock_pool: List[str]) -> Dict:
        """
        修复新浪K线数据的amount字段
        
        只修复：
        - 股票池中的股票
        - data_source=sina_kline
        - amount=0
        - 上一个已收盘交易日
        
        Args:
            stock_pool: 股票代码列表
        
        Returns:
            {'fixed': int, 'diffs': list}
        """
        from tradingagents.utils.trading_day_utils import TradingDayUtils
        from tradingagents.config.database_manager import get_database_manager
        
        results = {'fixed': 0, 'diffs': []}
        
        # 获取上一个已收盘交易日
        latest_closed = TradingDayUtils.get_latest_closed_trading_day()
        
        # 获取数据库连接
        db_manager = get_database_manager()
        mongodb_client = db_manager.get_mongodb_client()
        if mongodb_client is None:
            logger.error("MongoDB 客户端不可用")
            return results
        
        db = mongodb_client['tradingagents']
        
        logger.info(f"🔧 开始修复 sina_kline amount=0 的记录，日期: {latest_closed}")
        
        for symbol in stock_pool:
            try:
                # 查询需要修复的记录
                record = db.stock_daily_quotes.find_one({
                    "code": symbol,
                    "data_source": "sina_kline",
                    "trade_date": latest_closed,
                    "amount": 0
                })
                
                if not record:
                    continue
                
                # 从 AKShare/BaoStock 获取实时行情数据（含amount）
                realtime_data = None
                amount_source = None
                
                # 尝试 AKShare
                try:
                    akshare_provider = self._get_akshare_provider()
                    if akshare_provider:
                        realtime_quotes = await akshare_provider.get_stock_quotes(symbol)
                        if realtime_quotes and realtime_quotes.get('amount') is not None and realtime_quotes['amount'] > 0:
                            realtime_data = realtime_quotes
                            amount_source = realtime_quotes.get('quote_source', 'akshare_realtime')
                            logger.debug(f"📊 [{symbol}] AKShare实时行情: amount={realtime_quotes['amount']}")
                except Exception as e:
                    logger.warning(f"⚠️ [{symbol}] AKShare实时行情失败: {str(e)[:30]}")
                
                # 实时行情获取失败，保留 amount=0
                if realtime_data is None or realtime_data.get('amount') is None or realtime_data['amount'] <= 0:
                    logger.info(f"📝 [{symbol}] 实时行情无amount数据，保留原值0")
                    continue
                
                # 更新 amount（来自实时行情API）
                new_amount = realtime_data['amount']
                db.stock_daily_quotes.update_one(
                    {"_id": record["_id"]},
                    {"$set": {"amount": new_amount}}
                )
                
                results['fixed'] += 1
                logger.info(f"✅ [{symbol}] amount 更新: 0 -> {new_amount} ({amount_source})")
                
                # 对比差异
                diff_info = self._compare_and_log_diff(symbol, record, realtime_data, latest_closed)
                if diff_info:
                    results['diffs'].append(diff_info)
                
            except Exception as e:
                logger.error(f"❌ [{symbol}] 修复amount失败: {str(e)[:50]}")
        
        logger.info(f"🔧 amount修复完成: 固定 {results['fixed']} 条，差异 {len(results['diffs'])} 条")
        return results
    
    def _compare_and_log_diff(self, symbol: str, record: Dict, realtime: Dict, trade_date: str) -> Optional[str]:
        """
        对比已有数据与实时行情数据
        
        对比字段：open, high, low, close, volume
        差异阈值：相对差异 > 1%
        日志级别：WARNING
        
        Args:
            symbol: 股票代码
            record: 已有数据记录
            realtime: 实时行情数据
            trade_date: 交易日期
        
        Returns:
            差异信息字符串（如有差异）
        """
        fields = [
            ('open', '开盘价'),
            ('high', '最高价'),
            ('low', '最低价'),
            ('close', '收盘价'),
            ('volume', '成交量'),
        ]
        diffs = []
        
        for field, name in fields:
            old_val = record.get(field)
            new_val = realtime.get(field)
            
            if old_val is None or new_val is None:
                continue
            
            if old_val > 0:
                diff_pct = abs(new_val - old_val) / old_val * 100
                if diff_pct > 1.0:  # 差异超过 1%
                    diffs.append(f"{name}: {old_val} -> {new_val} ({diff_pct:.2f}%)")
        
        if diffs:
            diff_info = f"{symbol} {trade_date}: {', '.join(diffs)}"
            logger.warning(f"⚠️ 数据差异 {diff_info}")
            return diff_info
        
        return None
    
    async def _get_realtime_quotes_ef(self, symbol: str) -> Optional[Dict]:
        """
        使用东方财富实时行情 API 获取当天数据
        
        Args:
            symbol: 股票代码（如 601339）
        
        Returns:
            标准化的行情数据字典，失败返回 None
        """
        # 确定市场代码
        market = '1' if symbol.startswith('6') else '0'  # 沪市=1, 深市=0
        secid = f"{market}.{symbol}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Referer': 'http://quote.eastmoney.com/'
        }
        
        # 东方财富实时行情 API
        url = 'http://push2.eastmoney.com/api/qt/stock/get'
        params = {
            'secid': secid,
            'fields': 'f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f55,f56,f57,f58,f60',
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b'
        }
        
        try:
            resp = await asyncio.to_thread(
                requests.get, url, params=params, headers=headers, timeout=10
            )
            
            if resp.status_code != 200:
                logger.warning(f"⚠️ [{symbol}] 东方财富实时行情返回 {resp.status_code}")
                return None
            
            data = resp.json()
            if not data.get('data'):
                logger.warning(f"⚠️ [{symbol}] 东方财富实时行情无数据")
                return None
            
            # 解析字段
            raw = data['data']
            
            # 字段说明（值需要除以对应倍数）
            # f43: 最新价 ×100
            # f44: 最高价 ×100
            # f45: 最低价 ×100
            # f46: 今开价 ×100
            # f47: 成交量（手）
            # f48: 成交额（元）
            # f51: 昨收价 ×100
            # f52: 涨跌幅 ×100
            # f55: 换手率 ×100
            # f56: 动态市盈率 ×100
            # f58: 总市值
            # f60: 流通市值
            
            quotes = {
                'symbol': symbol,
                'code': symbol,
                'trade_date': datetime.now().strftime('%Y-%m-%d'),
                'open': raw.get('f46', 0) / 100 if raw.get('f46') else None,
                'close': raw.get('f43', 0) / 100 if raw.get('f43') else None,
                'high': raw.get('f44', 0) / 100 if raw.get('f44') else None,
                'low': raw.get('f45', 0) / 100 if raw.get('f45') else None,
                'pre_close': raw.get('f51', 0) / 100 if raw.get('f51') else None,
                'volume': raw.get('f47', 0) * 100 if raw.get('f47') else None,  # 手 → 股
                'amount': raw.get('f48', 0) if raw.get('f48') else None,
                'change_percent': raw.get('f52', 0) / 100 if raw.get('f52') else None,
                'turnover': raw.get('f55', 0) / 100 if raw.get('f55') else None,
                'pe_ttm': raw.get('f56', 0) / 100 if raw.get('f56') else None,
                'total_mv': raw.get('f58', 0) if raw.get('f58') else None,
                'circ_mv': raw.get('f60', 0) if raw.get('f60') else None,
                'data_source': 'eastmoney_realtime',
            }
            
            # 计算涨跌额
            if quotes['close'] and quotes['pre_close']:
                quotes['change'] = quotes['close'] - quotes['pre_close']
            
            # 计算振幅
            if quotes['high'] and quotes['low'] and quotes['pre_close']:
                quotes['amplitude'] = (quotes['high'] - quotes['low']) / quotes['pre_close'] * 100
            
            logger.info(f"✅ [{symbol}] 东方财富实时行情: close={quotes.get('close')}, volume={quotes.get('volume')}")
            return quotes
            
        except Exception as e:
            logger.warning(f"⚠️ [{symbol}] 东方财富实时行情失败: {str(e)[:50]}")
            return None
    
    def _convert_realtime_to_daily_format(self, quotes: Dict) -> pd.DataFrame:
        """
        将实时行情数据转换为日线数据格式
        
        Args:
            quotes: 实时行情字典
        
        Returns:
            DataFrame（与历史日线数据格式一致）
        """
        # 确保必要字段存在
        df = pd.DataFrame([{
            'trade_date': quotes.get('trade_date'),
            'date': quotes.get('trade_date'),  # 兼容不同字段名
            'code': quotes.get('code'),
            'symbol': quotes.get('symbol'),
            'open': quotes.get('open') or 0,
            'close': quotes.get('close') or 0,
            'high': quotes.get('high') or 0,
            'low': quotes.get('low') or 0,
            'pre_close': quotes.get('pre_close') or 0,
            'volume': quotes.get('volume') or 0,
            'amount': quotes.get('amount') or 0,
            'change_percent': quotes.get('change_percent') or 0,
            'change': quotes.get('change') or 0,
            'amplitude': quotes.get('amplitude') or 0,
            'turnover': quotes.get('turnover') or 0,
            'data_source': quotes.get('data_source', 'eastmoney_realtime'),
            'period': 'daily',
            'market': 'CN',
        }])
        
        return df
    
    async def sync_stock_pool(self, stock_pool: List[str]) -> Dict:
        """
        同步股票池的日线数据
        
        🔥 改进策略：
        - Gap <= 1 天 → 使用实时行情 API（更稳定）
        - Gap > 1 天 → 跳过，记录需要手动补充
        
        Args:
            stock_pool: 股票代码列表
        
        Returns:
            {'success': int, 'failed': int, 'skipped': int, 'errors': list, 'need_manual_sync': list}
        """
        
        from tradingagents.utils.trading_day_utils import TradingDayUtils
        
        results = {'success': 0, 'failed': 0, 'skipped': 0, 'errors': []}
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 检查是否收盘后
        if not TradingDayUtils.is_after_market_close():
            logger.warning("⚠️ 非收盘后时段，跳过同步")
            return results
        
        adapter = self._get_cache_adapter()
        
        # 计算同步范围（一年交易日）
        one_year_ago = TradingDayUtils.get_one_year_ago_trading_day()
        latest_closed = TradingDayUtils.get_latest_closed_trading_day()
        
        logger.info(f"📊 开始同步 {len(stock_pool)} 只股票，使用实时行情 API 补充当天数据")
        logger.info(f"⚙️ 重试配置: max_retries={self.max_retries}, request_interval={self.request_interval}s")
        logger.info(f"📅 最近已收盘交易日: {latest_closed}")
        
        # 重置需要手动补充的列表
        self.need_manual_sync = []
        
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
                
                # 🔥 判断 Gap 大小
                # 计算 Gap 天数
                gap_days = 0
                if metadata and metadata.get('latest_date'):
                    from datetime import datetime as dt
                    gap_days = (dt.strptime(latest_closed, '%Y-%m-%d') - 
                               dt.strptime(metadata['latest_date'], '%Y-%m-%d')).days
                
                # 🔥 策略调整：Gap <= 1 天 → 使用实时行情 API
                if gap_days <= 1:
                    # 使用实时行情 API 补充当天数据
                    await asyncio.sleep(self.request_interval)
                    
                    realtime_quotes = await self._get_realtime_quotes_ef(symbol)
                    
                    if realtime_quotes:
                        # 转换为日线格式
                        daily_data = self._convert_realtime_to_daily_format(realtime_quotes)
                        data = daily_data
                        data_source = 'eastmoney_realtime'
                        logger.info(f"✅ [{symbol}] 实时行情同步成功（Gap={gap_days}天）")
                    else:
                        results['failed'] += 1
                        results['errors'].append(f"{symbol}: 实时行情获取失败")
                        logger.warning(f"⚠️ [{symbol}] 实时行情获取失败")
                        continue
                
                # 🔥 Gap > 1 天 → 记录需要手动补充，跳过
                else:
                    self.need_manual_sync.append(symbol)
                    results['skipped'] += 1
                    logger.info(f"📝 [{symbol}] Gap={gap_days}天，需要手动补充历史数据，跳过自动同步")
                    continue
                
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
                    await asyncio.sleep(1)
                
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f"{symbol}: {str(e)[:50]}")
                logger.error(f"❌ [{symbol}] 同步失败: {str(e)[:50]}")
        
        logger.info(f"📊 同步完成: 成功={results['success']}, 失败={results['failed']}, 跳过={results['skipped']}")
        
        # 记录需要手动补充的股票
        if self.need_manual_sync:
            logger.info(f"📝 需要手动补充历史数据的股票 ({len(self.need_manual_sync)}只): {self.need_manual_sync[:20]}...")
            results['need_manual_sync'] = self.need_manual_sync
        
        # 失败超过 10% → 发送通知
        if results['failed'] > len(stock_pool) * 0.1:
            logger.warning(f"⚠️ 日线同步失败率 {results['failed']}/{len(stock_pool)}")
        
        # 🔥 新增：修复 sina_kline 数据的 amount 字段
        fix_results = await self.fix_sina_kline_amount(stock_pool)
        results['amount_fixed'] = fix_results.get('fixed', 0)
        results['amount_diffs'] = fix_results.get('diffs', [])
        
        return results


# 全局实例
_daily_quotes_sync_service = None


def get_daily_quotes_sync_service() -> DailyQuotesSyncService:
    """获取日线同步服务实例"""
    global _daily_quotes_sync_service
    if _daily_quotes_sync_service is None:
        _daily_quotes_sync_service = DailyQuotesSyncService()
    return _daily_quotes_sync_service


# ==================== 手动补充历史数据功能 ====================

async def manual_sync_historical_data(
    symbols: List[str],
    start_date: str,
    end_date: str,
    use_akshare: bool = True,
    use_baostock: bool = True
) -> Dict:
    """
    手动补充历史日线数据
    
    用于补充 Gap > 1 天的股票历史数据
    
    Args:
        symbols: 需要补充的股票代码列表
        start_date: 开始日期
        end_date: 结束日期
        use_akshare: 是否使用 AKShare
        use_baostock: 是否使用 BaoStock 备用
    
    Returns:
        同步结果 {'success': int, 'failed': int, 'errors': list}
    """
    service = get_daily_quotes_sync_service()
    adapter = service._get_cache_adapter()
    akshare = service._get_akshare_provider() if use_akshare else None
    baostock = service._get_baostock_provider() if use_baostock else None
    
    results = {'success': 0, 'failed': 0, 'errors': []}
    
    logger.info(f"📊 手动补充历史数据: {len(symbols)} 只股票，范围 {start_date} ~ {end_date}")
    
    for symbol in symbols:
        data = None
        data_source = None
        
        # 尝试 AKShare
        if akshare:
            try:
                data = await akshare.get_historical_data(symbol, start_date, end_date)
                if data and not data.empty:
                    data_source = 'akshare'
            except Exception as e:
                logger.warning(f"⚠️ [{symbol}] AKShare 失败: {str(e)[:50]}")
        
        # 尝试 BaoStock
        if data is None and baostock:
            try:
                data = await baostock.get_historical_data(symbol, start_date, end_date)
                if data and not data.empty:
                    data_source = 'baostock'
            except Exception as e:
                logger.warning(f"⚠️ [{symbol}] BaoStock 失败: {str(e)[:50]}")
        
        if data and not data.empty:
            adapter.save_historical_data_bulk(symbol, data, data_source)
            
            # 更新元数据
            actual_stats = adapter.get_historical_data_stats(symbol)
            adapter.update_cache_metadata(
                symbol=symbol,
                earliest_date=actual_stats.get('earliest_date'),
                latest_date=actual_stats.get('latest_date'),
                total_records=actual_stats.get('total_records', 0),
                is_complete=True,
                data_source=data_source
            )
            
            results['success'] += 1
            logger.info(f"✅ [{symbol}] 手动补充成功，{len(data)} 条")
        else:
            results['failed'] += 1
            results['errors'].append(f"{symbol}: 无法获取历史数据")
            logger.error(f"❌ [{symbol}] 手动补充失败")
        
        await asyncio.sleep(0.5)  # 避免 API 限流
    
    logger.info(f"📊 手动补充完成: 成功={results['success']}, 失败={results['failed']}")
    return results