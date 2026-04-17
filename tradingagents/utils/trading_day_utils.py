#!/usr/bin/env python3
"""
Trading Day Utilities
交易日判断工具类
"""
from datetime import datetime, timedelta
import logging

from tradingagents.calendar.trading_calendar import TradingCalendar, Market

logger = logging.getLogger(__name__)


class TradingDayUtils:
    """交易日判断工具类"""
    
    _calendar = None
    
    @classmethod
    def _get_calendar(cls):
        """获取交易日历实例"""
        if cls._calendar is None:
            cls._calendar = TradingCalendar()
        return cls._calendar
    
    @classmethod
    def get_one_year_ago_trading_day(cls) -> str:
        """
        获取一年前的交易日
        
        往前推365天，找到最近的交易日（往前找）
        
        Returns:
            str: 一年前的交易日 (YYYY-MM-DD)
        """
        calendar = cls._get_calendar()
        today = datetime.now()
        one_year_ago_date = (today - timedelta(days=365)).strftime('%Y-%m-%d')
        
        # 找到一年前最近的交易日（往前找）
        result = calendar.get_previous_trading_day(Market.CN, one_year_ago_date)
        logger.debug(f"一年前交易日: {one_year_ago_date} → {result}")
        return result
    
    @classmethod
    def get_latest_closed_trading_day(cls) -> str:
        """
        获取最近已收盘的交易日
        
        规则：
        - 交易日盘中 → 上一个交易日（今日未收盘）
        - 交易日收盘后 → 今天（今日已收盘）
        - 非交易日 → 上一个交易日
        
        Returns:
            str: 最近已收盘交易日 (YYYY-MM-DD)
        """
        calendar = cls._get_calendar()
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        
        # 检查今天是否是交易日
        is_trading_day = calendar.is_trading_day(Market.CN, today)
        
        # 盘中（交易时间内：9:30-15:00）
        if is_trading_day and cls._is_trading_time(now):
            # 最近已收盘的是上一个交易日
            result = calendar.get_previous_trading_day(Market.CN, today)
            logger.debug(f"盘中，最近已收盘交易日: {result}")
            return result
        
        # 盘后（15:00之后）
        if is_trading_day and cls._is_after_market_close(now):
            # 收盘后，今天已收盘
            logger.debug(f"收盘后，最近已收盘交易日: {today}")
            return today
        
        # 盘前或盘中（开盘前或交易时间内）→ 今天未收盘
        if is_trading_day and not cls._is_after_market_close(now):
            # 今天未收盘，返回上一个交易日
            result = calendar.get_previous_trading_day(Market.CN, today)
            logger.debug(f"盘前/盘中，最近已收盘交易日: {result}")
            return result
        
        # 非交易日（周末/节假日）
        if not is_trading_day:
            # 最近已收盘的是上一个交易日
            result = calendar.get_previous_trading_day(Market.CN, today)
            logger.debug(f"非交易日，最近已收盘交易日: {result}")
            return result
        
        return today
    
    @classmethod
    def _is_trading_time(cls, now: datetime) -> bool:
        """
        检查是否在交易时间内（9:30-11:30, 13:00-15:00）
        
        Args:
            now: 当前时间
        
        Returns:
            bool: 是否在交易时间
        """
        hour = now.hour
        minute = now.minute
        
        # 早盘：9:30-11:30
        if hour == 9 and minute >= 30:
            return True
        if hour == 10:
            return True
        if hour == 11 and minute <= 30:
            return True
        
        # 下午：13:00-15:00
        if hour == 13:
            return True
        if hour == 14:
            return True
        if hour == 15 and minute == 0:
            return True
        
        return False
    
    @classmethod
    def _is_after_market_close(cls, now: datetime) -> bool:
        """
        检查是否收盘后（15:00 之后）
        
        Args:
            now: 当前时间
        
        Returns:
            bool: 是否收盘后
        """
        return now.hour >= 15
    
    @classmethod
    def is_after_market_close(cls) -> bool:
        """
        检查是否收盘后（15:00 之后）
        
        Returns:
            bool: 是否收盘后
        """
        return cls._is_after_market_close(datetime.now())
    
    @classmethod
    def get_yesterday_trading_day(cls) -> str:
        """
        获取昨天的交易日（上一个交易日）
        
        Returns:
            str: 上一个交易日 (YYYY-MM-DD)
        """
        calendar = cls._get_calendar()
        today = datetime.now().strftime('%Y-%m-%d')
        return calendar.get_previous_trading_day(Market.CN, today)