#!/usr/bin/env python3
"""
新浪 K 线数据同步服务
从新浪财经 API 获取历史日线数据并同步到 MongoDB
"""
import asyncio
import json
import logging
import random
import requests
from datetime import datetime
from typing import Dict, List, Optional, Any

from app.core.database import get_mongo_db
from tradingagents.utils.trading_day_utils import TradingDayUtils

logger = logging.getLogger(__name__)


class SinaKlineSyncService:
    """新浪 K 线数据同步服务"""

    # 常量
    SINA_API_URL = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    MAX_DATALEN = 1023
    SCALE_DAILY = 240
    REQUEST_INTERVAL_MIN = 1.5  # 最小间隔（秒）
    REQUEST_INTERVAL_MAX = 1.5  # 最大间隔（秒）
    BATCH_SIZE = 60             # 每 N 个请求后暂停
    BATCH_PAUSE_SECONDS = 300   # 暂停时间（5 分钟）

    def __init__(self):
        """初始化服务"""
        self.db = None
        self.request_count = 0  # 请求计数器（用于批量限流保护）
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://finance.sina.com.cn/'
        }

    async def initialize(self):
        """异步初始化数据库连接"""
        try:
            self.db = get_mongo_db()
            logger.info("✅ SinaKlineSyncService 初始化成功")
        except Exception as e:
            logger.error(f"❌ SinaKlineSyncService 初始化失败: {e}")
            raise

    def _get_random_interval(self) -> float:
        """获取随机请求间隔（固定 1.5 秒）"""
        return random.uniform(self.REQUEST_INTERVAL_MIN, self.REQUEST_INTERVAL_MAX)

    def check_and_pause_batch(self) -> bool:
        """
        每 BATCH_SIZE 个请求后暂停 BATCH_PAUSE_SECONDS 秒

        Returns:
            True 表示发生了暂停，False 表示无需暂停
        """
        self.request_count += 1
        if self.request_count % self.BATCH_SIZE == 0:
            logger.info(
                f"⏸️ 批量限流保护: 已完成 {self.request_count} 个请求，"
                f"等待 {self.BATCH_PAUSE_SECONDS} 秒（{self.BATCH_PAUSE_SECONDS/60:.0f} 分钟）..."
            )
            import time
            time.sleep(self.BATCH_PAUSE_SECONDS)
            return True
        return False

    async def fetch_kline_from_sina(self, symbol: str, datalen: int = 1023) -> List[Dict]:
        """
        从新浪获取 K 线数据

        Args:
            symbol: 股票代码（如 601339）
            datalen: 数据长度（最大 1023）

        Returns:
            转换后的 MongoDB 格式数据列表
        """
        try:
            # 1. 确定市场前缀
            market = "sh" if symbol.startswith("6") else "sz"

            # 2. 限制 datalen
            datalen = min(datalen, self.MAX_DATALEN)

            # 3. 构建 URL
            url = f"{self.SINA_API_URL}?symbol={market}{symbol}&scale={self.SCALE_DAILY}&ma=no&datalen={datalen}"
            logger.debug(f"📡 请求新浪 API: {url}")

            # 4. 同步请求（在异步上下文中执行）
            def _sync_request():
                return requests.get(url, headers=self.headers, timeout=15)

            resp = await asyncio.to_thread(_sync_request)

            # 5. 检查响应
            if resp.status_code != 200:
                logger.warning(f"⚠️ 新浪 API 返回非 200 状态: {resp.status_code}")
                return []

            # 6. 解析 JSON
            try:
                raw_data = json.loads(resp.text)
            except json.JSONDecodeError as e:
                logger.error(f"❌ 新浪 API JSON 解析失败: {e}")
                return []

            # 7. 检查数据有效性
            if not raw_data or not isinstance(raw_data, list):
                logger.warning(f"⚠️ 新浪 API 返回空数据或非数组")
                return []

            # 8. 转换格式
            transformed = self._transform_data(raw_data, symbol)
            logger.info(f"✅ {symbol} 获取 {len(transformed)} 条 K 线数据")

            return transformed

        except requests.exceptions.Timeout:
            logger.error(f"❌ {symbol} 新浪 API 请求超时")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ {symbol} 新浪 API 请求失败: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ {symbol} 获取 K 线数据异常: {e}")
            return []

    def _transform_data(self, raw_data: List, symbol: str) -> List[Dict]:
        """
        转换新浪数据为 MongoDB 格式

        Args:
            raw_data: 新浪 API 返回的原始数据
            symbol: 股票代码

        Returns:
            转换后的 MongoDB 格式数据列表
        """
        result = []
        market_suffix = "SH" if symbol.startswith("6") else "SZ"
        now = datetime.utcnow()

        for i, item in enumerate(raw_data):
            try:
                # 构建基础文档
                doc = {
                    "symbol": symbol,
                    "code": symbol,
                    "full_symbol": f"{symbol}.{market_suffix}",
                    "market": "CN",
                    "trade_date": item.get("day", ""),
                    "period": "daily",
                    "data_source": "sina_kline",
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("close", 0)),
                    "volume": int(item.get("volume", 0)),
                    "amount": 0,  # 新浪无此字段，设为 0
                    "created_at": now,
                    "updated_at": now,
                    "version": 1,
                }

                # 计算 pre_close, change, pct_chg（第一条无昨收）
                if i > 0:
                    prev_close = float(raw_data[i - 1].get("close", 0))
                    doc["pre_close"] = prev_close
                    if prev_close > 0:
                        doc["change"] = round(doc["close"] - prev_close, 2)
                        doc["pct_chg"] = round(doc["change"] / prev_close * 100, 2)
                    else:
                        doc["change"] = None
                        doc["pct_chg"] = None
                else:
                    doc["pre_close"] = None
                    doc["change"] = None
                    doc["pct_chg"] = None

                result.append(doc)

            except (ValueError, TypeError) as e:
                logger.warning(f"⚠️ {symbol} 第 {i} 条数据转换失败: {e}")
                continue

        return result

    async def get_incomplete_stocks(self) -> List[str]:
        """
        获取股票池中不完整的股票列表
        
        股票池来源：Top120 + 当前持仓（由 stock_pool_service 提供）
        
        Returns:
            不完整股票代码列表
        """
        if self.db is None:
            await self.initialize()

        try:
            # 1. 获取股票池（Top120 + 持仓）
            from app.services.stock_pool_service import get_stock_pool_for_sync
            stock_pool = await get_stock_pool_for_sync()
            
            if not stock_pool:
                logger.warning("⚠️ 股票池为空")
                return []
            
            logger.info(f"📊 股票池: {len(stock_pool)} 只")
            
            # 2. 过滤出不完整的股票
            incomplete_stocks = []
            for symbol in stock_pool:
                # 🔥 直接从数据库统计判断，不再依赖 metadata
                stats = await self.db.stock_daily_quotes.aggregate([
                    {"$match": {"code": symbol}},
                    {"$group": {
                        "_id": None,
                        "earliest_date": {"$min": "$trade_date"},
                        "latest_date": {"$max": "$trade_date"},
                        "total_records": {"$sum": 1}
                    }}
                ]).to_list(None)
                
                if not stats:
                    incomplete_stocks.append(symbol)
                    continue
                
                # 判断完整性
                earliest = stats[0].get("earliest_date")
                latest = stats[0].get("latest_date")
                
                # 不完整的情况：earliest > 一年前 或 latest < 最近已收盘日
                one_year_ago = TradingDayUtils.get_one_year_ago_trading_day()
                latest_closed = TradingDayUtils.get_latest_closed_trading_day()
                
                if not earliest or not latest or earliest > one_year_ago or latest < latest_closed:
                    logger.info(f"⚠️ [{symbol}] 不完整: {earliest}~{latest}")
                    incomplete_stocks.append(symbol)
            
            logger.info(f"📋 查询到 {len(incomplete_stocks)} 只不完整股票")
            return incomplete_stocks

        except Exception as e:
            logger.error(f"❌ 查询不完整股票失败: {e}")
            return []

    async def sync_single_stock(self, symbol: str, datalen: int = 1023) -> Dict:
        """
        同步单只股票（增量更新）

        Args:
            symbol: 股票代码
            datalen: 数据长度

        Returns:
            同步结果 {symbol, new_records, status, error?}
        """
        if self.db is None:
            await self.initialize()

        try:
            # 1. 获取新浪数据
            sina_data = await self.fetch_kline_from_sina(symbol, datalen)

            if not sina_data:
                return {
                    "symbol": symbol,
                    "error": "无法获取新浪数据",
                    "status": "failed"
                }

            # 2. 查询已有数据的 trade_date
            existing_dates = set()
            cursor = self.db.stock_daily_quotes.find({"code": symbol}, {"trade_date": 1})
            for doc in await cursor.to_list(length=None):
                existing_dates.add(doc.get("trade_date"))

            # 3. 过滤新数据（增量）
            new_data = [d for d in sina_data if d["trade_date"] not in existing_dates]

            # 4. 批量插入新数据
            if new_data:
                try:
                    self.db.stock_daily_quotes.insert_many(new_data)
                    logger.info(f"✅ {symbol} 插入 {len(new_data)} 条新数据")
                except Exception as e:
                    logger.error(f"❌ {symbol} 批量插入失败: {e}")
                    return {
                        "symbol": symbol,
                        "error": f"插入失败: {str(e)[:50]}",
                        "status": "failed"
                    }

            # 5. 更新缓存元数据（异步）
            # 🔥 不再维护 metadata
            # await self._update_metadata(symbol, sina_data)

            # 6. 返回结果
            return {
                "symbol": symbol,
                "new_records": len(new_data),
                "total_records": len(sina_data),
                "status": "success" if len(new_data) > 0 else "skipped"
            }

        except Exception as e:
            logger.error(f"❌ {symbol} 同步失败: {e}")
            return {
                "symbol": symbol,
                "error": str(e)[:50],
                "status": "failed"
            }
    # 🔥 _update_metadata 方法已删除，不再维护 metadata
# 全局服务实例
_sina_kline_sync_service: Optional[SinaKlineSyncService] = None


async def get_sina_kline_sync_service() -> SinaKlineSyncService:
    """获取新浪 K 线同步服务实例"""
    global _sina_kline_sync_service
    if _sina_kline_sync_service is None:
        _sina_kline_sync_service = SinaKlineSyncService()
        await _sina_kline_sync_service.initialize()
    return _sina_kline_sync_service
