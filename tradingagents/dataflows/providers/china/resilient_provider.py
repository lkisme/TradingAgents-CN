#!/usr/bin/env python3
"""
Resilient China Stock Provider
带自动降级的中国股票数据提供器，AKShare失败时自动切换BaoStock
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Union
import pandas as pd

from ..base_provider import BaseStockDataProvider

logger = logging.getLogger(__name__)


class ResilientChinaStockProvider(BaseStockDataProvider):
    """
    带冗余的中国股票数据提供器
    
    特性:
    - AKShare失败时自动切换BaoStock
    - BaoStock也失败才报错
    - 清晰的日志记录
    - 数据格式标准化
    """
    
    def __init__(self, source_priority: List[str] = None):
        """
        初始化Resilient Provider
        
        Args:
            source_priority: 数据源优先级列表，默认 ['akshare', 'baostock']
        """
        super().__init__("resilient_china")
        
        # 数据源优先级（可配置）
        self._source_priority = source_priority or ["akshare", "baostock"]
        
        # 当前使用的数据源
        self._current_source = None
        
        # 初始化子提供器
        self._providers = {}
        self._init_providers()
        
        logger.info(f"🔧 ResilientChinaStockProvider 初始化完成")
        logger.info(f"   数据源优先级: {self._source_priority}")
    
    def _init_providers(self):
        """初始化子提供器"""
        # 初始化 AKShare Provider
        try:
            from .akshare import AKShareProvider, get_akshare_provider
            self._providers["akshare"] = get_akshare_provider()
            if self._providers["akshare"].connected:
                logger.info(f"✅ AKShare Provider 初始化成功")
            else:
                logger.warning(f"⚠️ AKShare Provider 未连接")
        except Exception as e:
            logger.warning(f"⚠️ AKShare Provider 初始化失败: {e}")
            self._providers["akshare"] = None
        
        # 初始化 BaoStock Provider
        try:
            from .baostock import BaoStockProvider, get_baostock_provider
            self._providers["baostock"] = get_baostock_provider()
            if self._providers["baostock"].connected:
                logger.info(f"✅ BaoStock Provider 初始化成功")
            else:
                logger.warning(f"⚠️ BaoStock Provider 未连接")
        except Exception as e:
            logger.warning(f"⚠️ BaoStock Provider 初始化失败: {e}")
            self._providers["baostock"] = None
    
    async def connect(self) -> bool:
        """连接到数据源"""
        # 检查是否有可用的提供器
        available_providers = [
            name for name, provider in self._providers.items()
            if provider is not None and provider.connected
        ]
        
        if available_providers:
            self.connected = True
            logger.info(f"✅ Resilient Provider 连接成功，可用数据源: {available_providers}")
            return True
        else:
            self.connected = False
            logger.error(f"❌ Resilient Provider 连接失败，无可用数据源")
            return False
    
    async def test_connection(self) -> bool:
        """测试连接"""
        return await self.connect()
    
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        return any(
            provider is not None and provider.connected
            for provider in self._providers.values()
        )
    
    def get_current_source(self) -> Optional[str]:
        """获取当前使用的数据源"""
        return self._current_source
    
    async def get_historical_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        period: str = "daily"
    ) -> Optional[pd.DataFrame]:
        """
        获取历史行情数据，带自动降级
        
        Args:
            code: 股票代码（6位数字，如 600519）
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 周期 (daily, weekly, monthly)
        
        Returns:
            历史行情数据DataFrame，标准化列名: date, open, close, high, low, volume, amount
        """
        logger.info(f"📊 [Resilient Provider] 开始获取历史数据: {code} ({start_date} 到 {end_date})")
        
        # 添加详细的股票代码追踪日志
        logger.debug(f"🔍 [股票代码追踪] 输入代码: '{code}' (类型: {type(code)}, 长度: {len(str(code))})")
        
        for source_name in self._source_priority:
            provider = self._providers.get(source_name)
            
            if provider is None or not provider.connected:
                logger.warning(f"⚠️ [{source_name}] Provider 未初始化或未连接，跳过")
                continue
            
            try:
                logger.info(f"🔄 [{source_name}] 尝试获取历史数据: {code}")
                
                # 调用子提供器的获取方法
                df = await provider.get_historical_data(code, start_date, end_date, period)
                
                # 检查结果
                if df is not None and not df.empty:
                    # 标准化数据格式
                    df = self._standardize_data_format(df, code, source_name)
                    
                    # 记录成功的数据源
                    self._current_source = source_name
                    
                    logger.info(f"✅ [{source_name}] 历史数据获取成功: {code}, {len(df)}条记录")
                    return df
                else:
                    logger.warning(f"⚠️ [{source_name}] 返回空数据: {code}")
                    continue
                    
            except Exception as e:
                error_msg = str(e)
                
                # 🔥 判断是否是限流错误
                is_rate_limit = self._is_rate_limit_error(error_msg)
                
                if is_rate_limit:
                    logger.warning(f"⚠️ [{source_name}] 限流错误: {code} - {error_msg}")
                    logger.info(f"🔄 [{source_name}] 限流触发，自动切换到下一个数据源")
                else:
                    logger.warning(f"⚠️ [{source_name}] 获取失败: {code} - {error_msg}")
                
                continue
        
        # 所有数据源都失败
        logger.error(f"❌ 所有数据源均失败: {code}")
        self._current_source = None
        return None
    
    def _is_rate_limit_error(self, error_msg: str) -> bool:
        """
        判断是否是限流错误
        
        Args:
            error_msg: 错误消息
        
        Returns:
            bool: 是否是限流错误
        """
        rate_limit_keywords = [
            'Connection aborted',
            'Remote end closed connection',
            '429',  # Too Many Requests
            'rate limit',
            '限流',
            'too many requests',
            'service unavailable',
            '503',
            'timeout',
            'ETIMEDOUT',
            'ECONNRESET',
            'SSL',
            'UNEXPECTED_EOF_WHILE_READING'
        ]
        
        return any(keyword.lower() in error_msg.lower() for keyword in rate_limit_keywords)
    
    def _standardize_data_format(self, df: pd.DataFrame, code: str, source_name: str) -> pd.DataFrame:
        """
        标准化数据格式
        
        Args:
            df: 原始DataFrame
            code: 股票代码
            source_name: 数据源名称
        
        Returns:
            标准化后的DataFrame，列名: date, open, close, high, low, volume, amount, turnover, change_percent
        """
        try:
            # 复制DataFrame避免修改原始数据
            df = df.copy()
            
            # 🔥 标准化列名映射（根据数据源）
            if source_name == "akshare":
                # AKShare 列名映射
                column_mapping = {
                    '日期': 'date',
                    '开盘': 'open',
                    '收盘': 'close',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'volume',
                    '成交额': 'amount',
                    '振幅': 'amplitude',
                    '涨跌幅': 'change_percent',
                    '涨跌额': 'change',
                    '换手率': 'turnover'
                }
            elif source_name == "baostock":
                # BaoStock 列名映射
                column_mapping = {
                    'date': 'date',
                    'open': 'open',
                    'close': 'close',
                    'high': 'high',
                    'low': 'low',
                    'volume': 'volume',
                    'amount': 'amount',
                    'pctChg': 'change_percent',
                    'turn': 'turnover',
                    'preclose': 'pre_close'
                }
            else:
                # 默认映射（保留英文列名）
                column_mapping = {}
            
            # 应用列名映射
            df = df.rename(columns=column_mapping)
            
            # 🔥 确保关键列存在并转换为数值类型
            numeric_columns = ['open', 'close', 'high', 'low', 'volume', 'amount']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            # 确保日期格式正确
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
            
            # 🔥 添加标准化字段
            df['code'] = code
            df['full_symbol'] = self._get_full_symbol(code)
            df['data_source'] = source_name
            
            # 按日期排序
            df = df.sort_values('date')
            
            logger.debug(f"✅ [{source_name}] 数据标准化完成: {len(df)}条记录")
            return df
            
        except Exception as e:
            logger.error(f"❌ 数据标准化失败: {e}")
            return df
    
    def _get_full_symbol(self, code: str) -> str:
        """
        获取完整股票代码
        
        Args:
            code: 6位股票代码
        
        Returns:
            完整标准化代码 (600519.SS / 000001.SZ)
        """
        if not code:
            return ""
        
        code = str(code).strip()
        
        # 根据代码前缀判断交易所
        if code.startswith(('6', '9')):
            return f"{code}.SS"
        elif code.startswith(('0', '3', '2')):
            return f"{code}.SZ"
        elif code.startswith(('8', '4')):
            return f"{code}.BJ"
        else:
            return code
    
    async def get_stock_basic_info(self, code: str) -> Dict[str, Any]:
        """
        获取股票基础信息，带自动降级
        
        Args:
            code: 股票代码
        
        Returns:
            标准化的股票基础信息
        """
        for source_name in self._source_priority:
            provider = self._providers.get(source_name)
            
            if provider is None or not provider.connected:
                continue
            
            try:
                info = await provider.get_stock_basic_info(code)
                
                if info and info.get('name'):
                    self._current_source = source_name
                    logger.info(f"✅ [{source_name}] 基础信息获取成功: {code}")
                    return info
                    
            except Exception as e:
                logger.warning(f"⚠️ [{source_name}] 基础信息获取失败: {code} - {e}")
                continue
        
        # 返回默认信息
        return {
            "code": code,
            "name": f"股票{code}",
            "industry": "未知",
            "area": "未知",
            "data_source": "unknown"
        }
    
    async def get_stock_quotes(self, code: str) -> Dict[str, Any]:
        """
        获取实时行情，带自动降级
        
        Args:
            code: 股票代码
        
        Returns:
            标准化的实时行情数据
        """
        for source_name in self._source_priority:
            provider = self._providers.get(source_name)
            
            if provider is None or not provider.connected:
                continue
            
            try:
                quotes = await provider.get_stock_quotes(code)
                
                if quotes and quotes.get('price'):
                    self._current_source = source_name
                    logger.info(f"✅ [{source_name}] 实时行情获取成功: {code}")
                    return quotes
                    
            except Exception as e:
                logger.warning(f"⚠️ [{source_name}] 实时行情获取失败: {code} - {e}")
                continue
        
        # 返回空行情
        return {}
    
    async def get_stock_list(self) -> List[Dict[str, Any]]:
        """
        获取股票列表
        
        Returns:
            股票列表，包含代码和名称
        """
        # 尝试从第一个可用的数据源获取
        for source_name in self._source_priority:
            provider = self._providers.get(source_name)
            
            if provider is None or not provider.connected:
                continue
            
            try:
                stock_list = await provider.get_stock_list()
                
                if stock_list:
                    self._current_source = source_name
                    logger.info(f"✅ [{source_name}] 股票列表获取成功: {len(stock_list)}只")
                    return stock_list
                    
            except Exception as e:
                logger.warning(f"⚠️ [{source_name}] 股票列表获取失败: {e}")
                continue
        
        return []
    
    async def get_financial_data(self, code: str, year: Optional[int] = None, quarter: Optional[int] = None) -> Dict[str, Any]:
        """
        获取财务数据，带自动降级
        
        Args:
            code: 股票代码
            year: 年份
            quarter: 季度
        
        Returns:
            财务数据字典
        """
        for source_name in self._source_priority:
            provider = self._providers.get(source_name)
            
            if provider is None or not provider.connected:
                continue
            
            try:
                # 尝试调用子提供器的财务数据方法
                if hasattr(provider, 'get_financial_data'):
                    financial_data = await provider.get_financial_data(code, year, quarter)
                    
                    if financial_data:
                        self._current_source = source_name
                        logger.info(f"✅ [{source_name}] 财务数据获取成功: {code}")
                        return financial_data
                    
            except Exception as e:
                logger.warning(f"⚠️ [{source_name}] 财务数据获取失败: {code} - {e}")
                continue
        
        return {}
    
    async def get_valuation_data(self, code: str, trade_date: Optional[str] = None) -> Dict[str, Any]:
        """
        获取估值数据（PE、PB等）
        
        Args:
            code: 股票代码
            trade_date: 交易日期
        
        Returns:
            估值数据字典
        """
        # BaoStock 有估值数据接口，优先使用
        provider = self._providers.get("baostock")
        
        if provider is not None and provider.connected:
            try:
                if hasattr(provider, 'get_valuation_data'):
                    valuation_data = await provider.get_valuation_data(code, trade_date)
                    
                    if valuation_data:
                        self._current_source = "baostock"
                        logger.info(f"✅ [baostock] 估值数据获取成功: {code}")
                        return valuation_data
                    
            except Exception as e:
                logger.warning(f"⚠️ [baostock] 估值数据获取失败: {code} - {e}")
        
        return {}
    
    async def get_fundamentals_data(
        self,
        code: str,
        year: Optional[int] = None,
        quarter: Optional[int] = None,
        data_type: str = "profit"
    ) -> Dict[str, Any]:
        """
        Phase 2: 获取财务数据（基本面数据），带自动降级
        
        AKShare 失败时切换到 BaoStock 业绩数据 API
        
        Args:
            code: 股票代码
            year: 年份（默认当前年份）
            quarter: 季度（默认当前季度）
            data_type: 数据类型 ("profit", "growth", "operation", "balance", "cash_flow")
        
        Returns:
            标准化的财务数据字典
        """
        logger.info(f"💰 [Resilient Provider] 开始获取财务数据: {code} (类型: {data_type})")
        
        # 设置默认年份和季度
        if year is None:
            year = datetime.now().year
        if quarter is None:
            current_month = datetime.now().month
            quarter = (current_month - 1) // 3 + 1
        
        # 🔥 Phase 2 实现：财务数据冗余
        # 优先级：AKShare > BaoStock
        
        # 1. 尝试 AKShare（如果有财务数据接口）
        akshare_provider = self._providers.get("akshare")
        if akshare_provider is not None and akshare_provider.connected:
            try:
                logger.info(f"🔄 [akshare] 尝试获取财务数据: {code}")
                
                # AKShare 财务数据接口（如果存在）
                if hasattr(akshare_provider, 'get_fundamentals_data'):
                    fundamentals_data = await akshare_provider.get_fundamentals_data(
                        code, year, quarter, data_type
                    )
                    
                    if fundamentals_data and not self._is_empty_data(fundamentals_data):
                        self._current_source = "akshare"
                        logger.info(f"✅ [akshare] 财务数据获取成功: {code}")
                        return self._standardize_fundamentals_data(fundamentals_data, code, "akshare")
                
            except Exception as e:
                error_msg = str(e)
                is_rate_limit = self._is_rate_limit_error(error_msg)
                
                if is_rate_limit:
                    logger.warning(f"⚠️ [akshare] 限流错误，切换到 BaoStock: {code} - {error_msg}")
                else:
                    logger.warning(f"⚠️ [akshare] 财务数据获取失败: {code} - {error_msg}")
        
        # 2. 切换到 BaoStock（财务数据备用）
        baostock_provider = self._providers.get("baostock")
        if baostock_provider is not None and baostock_provider.connected:
            try:
                logger.info(f"🔄 [baostock] 尝试获取财务数据: {code}")
                
                # BaoStock 业绩数据接口
                fundamentals_data = await self._get_baostock_fundamentals(
                    baostock_provider, code, year, quarter, data_type
                )
                
                if fundamentals_data and not self._is_empty_data(fundamentals_data):
                    self._current_source = "baostock"
                    logger.info(f"✅ [baostock] 财务数据获取成功（备用源）: {code}")
                    return self._standardize_fundamentals_data(fundamentals_data, code, "baostock")
                
            except Exception as e:
                logger.warning(f"⚠️ [baostock] 财务数据获取失败: {code} - {e}")
        
        # 所有数据源都失败
        logger.error(f"❌ 所有数据源均失败: {code} 财务数据")
        self._current_source = None
        return {}
    
    async def _get_baostock_fundamentals(
        self,
        provider,
        code: str,
        year: int,
        quarter: int,
        data_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        从 BaoStock 获取财务数据
        
        使用 BaoStock 的 query_profit_data / query_growth_data 等 API
        
        Args:
            provider: BaoStock Provider 实例
            code: 股票代码
            year: 年份
            quarter: 季度
            data_type: 数据类型
        
        Returns:
            财务数据字典
        """
        try:
            # 根据数据类型调用不同的 BaoStock API
            if data_type == "profit":
                # 盈利能力数据
                return await provider._get_profit_data(code, year, quarter)
            elif data_type == "growth":
                # 成长能力数据
                return await provider._get_growth_data(code, year, quarter)
            elif data_type == "operation":
                # 营运能力数据
                return await provider._get_operation_data(code, year, quarter)
            elif data_type == "balance":
                # 偿债能力数据
                return await provider._get_balance_data(code, year, quarter)
            elif data_type == "cash_flow":
                # 现金流量数据
                return await provider._get_cash_flow_data(code, year, quarter)
            else:
                # 默认获取盈利能力数据
                logger.warning(f"⚠️ 未知的数据类型: {data_type}，使用默认盈利能力数据")
                return await provider._get_profit_data(code, year, quarter)
                
        except Exception as e:
            logger.error(f"❌ BaoStock 财务数据获取失败: {e}")
            return None
    
    def _standardize_fundamentals_data(
        self,
        data: Dict[str, Any],
        code: str,
        source_name: str
    ) -> Dict[str, Any]:
        """
        标准化财务数据格式
        
        Args:
            data: 原始财务数据
            code: 股票代码
            source_name: 数据源名称
        
        Returns:
            标准化的财务数据
        """
        try:
            # 添加元数据
            standardized_data = {
                "code": code,
                "full_symbol": self._get_full_symbol(code),
                "data_source": source_name,
                "year": data.get("year", datetime.now().year),
                "quarter": data.get("quarter", (datetime.now().month - 1) // 3 + 1),
                "fetch_time": datetime.now(timezone.utc).isoformat(),
            }
            
            # 合合原始数据
            standardized_data.update(data)
            
            logger.debug(f"✅ [{source_name}] 财务数据标准化完成: {code}")
            return standardized_data
            
        except Exception as e:
            logger.error(f"❌ 财务数据标准化失败: {e}")
            return data
    
    def _is_empty_data(self, data: Dict[str, Any]) -> bool:
        """
        检查数据是否为空
        
        Args:
            data: 数据字典
        
        Returns:
            bool: 是否为空数据
        """
        if not data:
            return True
        
        # 检查是否只有元数据字段
        meta_fields = ["code", "full_symbol", "data_source", "year", "quarter", "fetch_time"]
        actual_data_fields = [k for k in data.keys() if k not in meta_fields]
        
        return len(actual_data_fields) == 0
    
    async def get_news_data(
        self,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Phase 3: 获取新闻数据
        
        评估结果：BaoStock 无直接新闻 API，但可以通过其他方式获取
        
        实现策略：
        1. AKShare 东方财富新闻（主要）
        2. AKShare 财经新闻（备用）
        3. 暂不使用 BaoStock（无新闻接口）
        
        Args:
            code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            新闻列表
        """
        logger.info(f"📰 [Resilient Provider] 开始获取新闻数据: {code}")
        
        # 设置默认日期范围
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        # 🔥 Phase 3 实现：新闻数据冗余评估
        # 
        # 评估结论：
        # - BaoStock 无直接新闻 API
        # - AKShare 有多个新闻接口（东方财富、财经新闻等）
        # - 建议使用 AKShare 多个新闻接口实现冗余
        # - 如果 AKShare 也失败，可以考虑第三方新闻源（如 Google News）
        
        news_list = []
        
        # 1. 尝试 AKShare 东方财富新闻
        akshare_provider = self._providers.get("akshare")
        if akshare_provider is not None and akshare_provider.connected:
            try:
                logger.info(f"🔄 [akshare] 尝试获取东方财富新闻: {code}")
                
                if hasattr(akshare_provider, 'get_stock_news_sync'):
                    # 使用同步方法（需要包装为异步）
                    news_df = await asyncio.to_thread(
                        akshare_provider.get_stock_news_sync,
                        symbol=code
                    )
                    
                    if news_df is not None and not news_df.empty:
                        # 转换为标准格式
                        news_items = self._convert_news_df_to_list(news_df, code, "akshare_em")
                        news_list.extend(news_items)
                        self._current_source = "akshare"
                        logger.info(f"✅ [akshare] 东方财富新闻获取成功: {code}, {len(news_items)}条")
                        return news_items
                        
            except Exception as e:
                error_msg = str(e)
                is_rate_limit = self._is_rate_limit_error(error_msg)
                
                if is_rate_limit:
                    logger.warning(f"⚠️ [akshare] 新闻接口限流: {code} - {error_msg}")
                else:
                    logger.warning(f"⚠️ [akshare] 新闻获取失败: {code} - {error_msg}")
        
        # 2. Phase 3 评估结论
        # 
        # 由于 BaoStock 无新闻 API，有以下选择：
        # - 选择 A: 添加第三方新闻源（如 Google News API）
        # - 选择 B: 暂时跳过新闻冗余，仅依赖 AKShare
        # - 选择 C: 使用现有的 interface.get_google_news 作为备用
        
        # 当前实现：返回获取到的新闻或空列表
        # 未来可扩展：添加 Google News 或其他新闻源
        
        if not news_list:
            logger.warning(f"⚠️ [Phase 3] 新闻数据暂无可用备用源，建议添加第三方新闻 API")
            self._current_source = None
        
        return news_list
    
    def _convert_news_df_to_list(
        self,
        news_df: pd.DataFrame,
        code: str,
        source_name: str
    ) -> List[Dict[str, Any]]:
        """
        将新闻 DataFrame 转换为标准列表格式
        
        Args:
            news_df: 新闻 DataFrame
            code: 股票代码
            source_name: 数据源名称
        
        Returns:
            标准化的新闻列表
        """
        try:
            news_list = []
            
            for _, row in news_df.iterrows():
                # 根据数据源解析字段
                if source_name == "akshare_em":
                    # AKShare 东方财富新闻字段
                    news_item = {
                        "title": row.get('新闻标题', row.get('标题', '')),
                        "content": row.get('新闻内容', row.get('内容', '')),
                        "time": row.get('发布时间', row.get('时间', '')),
                        "url": row.get('新闻链接', row.get('链接', '')),
                        "source": "东方财富",
                        "code": code,
                        "data_source": source_name,
                    }
                else:
                    # 默认格式
                    news_item = {
                        "title": str(row.iloc[0]) if len(row) > 0 else '',
                        "content": str(row.iloc[1]) if len(row) > 1 else '',
                        "time": str(row.iloc[2]) if len(row) > 2 else '',
                        "url": str(row.iloc[3]) if len(row) > 3 else '',
                        "source": source_name,
                        "code": code,
                    }
                
                news_list.append(news_item)
            
            return news_list
            
        except Exception as e:
            logger.error(f"❌ 新闻数据转换失败: {e}")
            return []


# 全局提供器实例
_resilient_provider = None


def get_resilient_provider() -> ResilientChinaStockProvider:
    """获取全局Resilient Provider实例"""
    global _resilient_provider
    if _resilient_provider is None:
        _resilient_provider = ResilientChinaStockProvider()
    return _resilient_provider