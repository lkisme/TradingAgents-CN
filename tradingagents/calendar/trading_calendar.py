#!/usr/bin/env python3
"""
Trading Calendar
交易日历工具，提供交易日判断功能
"""
from datetime import datetime, timedelta
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class Market(Enum):
    """市场类型枚举"""
    CN = "CN"  # 中国A股
    US = "US"  # 美股
    HK = "HK"  # 港股


class TradingCalendar:
    """
    交易日历工具类
    
    功能：
    - 判断是否是交易日
    - 获取上一个/下一个交易日
    - 获取交易日列表
    
    注意：当前实现为简化版本，只处理周末（周六、周日）
    未来可以扩展为完整的交易日历（包含节假日）
    """
    
    # 中国A股节假日列表（2024-2026）
    # 未来可以从数据库或API获取完整的节假日列表
    CN_HOLIDAYS_2024 = [
        "2024-01-01",  # 元旦
        "2024-02-09", "2024-02-10", "2024-02-11", "2024-02-12", "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16", "2024-02-17",  # 春节
        "2024-04-04", "2024-04-05", "2024-04-06",  # 清明节
        "2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-05",  # 劳动节
        "2024-06-08", "2024-06-09", "2024-06-10",  # 端午节
        "2024-09-15", "2024-09-16", "2024-09-17",  # 中秋节
        "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04", "2024-10-05", "2024-10-06", "2024-10-07",  # 国庆节
    ]
    
    CN_HOLIDAYS_2025 = [
        "2025-01-01",  # 元旦
        # 春节（2025年具体日期待更新）
        "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31", "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",  # 春节（预测）
        # 清明节
        "2025-04-04", "2025-04-05", "2025-04-06",
        # 劳动节
        "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
        # 端午节
        "2025-06-08", "2025-06-09", "2025-06-10",
        # 中秋节
        "2025-09-15", "2025-09-16", "2025-09-17",
        # 国庆节
        "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04", "2025-10-05", "2025-10-06", "2025-10-07",
    ]
    
    CN_HOLIDAYS_2026 = [
        "2026-01-01",  # 元旦
        # 春节（预测）
        "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
        # 清明节
        "2026-04-04", "2026-04-05", "2026-04-06",
        # 劳动节
        "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
        # 端午节
        "2026-06-08", "2026-06-09", "2026-06-10",
        # 中秋节
        "2026-09-15", "2026-09-16", "2026-09-17",
        # 国庆节
        "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07",
    ]
    
    def __init__(self):
        """初始化交易日历"""
        # 合并所有年份的节假日
        self.cn_holidays = set()
        self.cn_holidays.update(self.CN_HOLIDAYS_2024)
        self.cn_holidays.update(self.CN_HOLIDAYS_2025)
        self.cn_holidays.update(self.CN_HOLIDAYS_2026)
        
        logger.info(f"✅ TradingCalendar 初始化完成，已加载 {len(self.cn_holidays)} 个节假日")
    
    def is_trading_day(self, market: Market, date_str: str) -> bool:
        """
        判断是否是交易日
        
        Args:
            market: 市场类型
            date_str: 日期字符串 (YYYY-MM-DD)
        
        Returns:
            bool: 是否是交易日
        """
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d')
            
            if market == Market.CN:
                # 1. 检查周末
                if date.weekday() >= 5:  # 周六(5)或周日(6)
                    logger.debug(f"[{date_str}] 不是交易日（周末）")
                    return False
                
                # 2. 检查节假日
                if date_str in self.cn_holidays:
                    logger.debug(f"[{date_str}] 不是交易日（节假日）")
                    return False
                
                return True
            
            elif market == Market.US:
                # 美股：只检查周末
                if date.weekday() >= 5:
                    logger.debug(f"[{date_str}] 不是交易日（周末）")
                    return False
                return True
            
            elif market == Market.HK:
                # 港股：只检查周末（简化版）
                if date.weekday() >= 5:
                    logger.debug(f"[{date_str}] 不是交易日（周末）")
                    return False
                return True
            
            else:
                logger.warning(f"未知的市场类型: {market}")
                return False
            
        except Exception as e:
            logger.error(f"日期格式错误: {date_str}, {e}")
            return False
    
    def get_previous_trading_day(self, market: Market, date_str: str) -> str:
        """
        获取上一个交易日
        
        Args:
            market: 市场类型
            date_str: 日期字符串 (YYYY-MM-DD)
        
        Returns:
            str: 上一个交易日 (YYYY-MM-DD)
        """
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d')
            
            # 向前查找（最多30天）
            for i in range(1, 31):
                prev_date = date - timedelta(days=i)
                prev_date_str = prev_date.strftime('%Y-%m-%d')
                
                if self.is_trading_day(market, prev_date_str):
                    logger.debug(f"[{date_str}] 上一个交易日: {prev_date_str}")
                    return prev_date_str
            
            # 找不到交易日，返回30天前
            logger.warning(f"[{date_str}] 未找到上一个交易日，返回30天前")
            fallback_date = (date - timedelta(days=30)).strftime('%Y-%m-%d')
            return fallback_date
            
        except Exception as e:
            logger.error(f"获取上一个交易日失败: {e}")
            return date_str
    
    def get_next_trading_day(self, market: Market, date_str: str) -> str:
        """
        获取下一个交易日
        
        Args:
            market: 市场类型
            date_str: 日期字符串 (YYYY-MM-DD)
        
        Returns:
            str: 下一个交易日 (YYYY-MM-DD)
        """
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d')
            
            # 向后查找（最多30天）
            for i in range(1, 31):
                next_date = date + timedelta(days=i)
                next_date_str = next_date.strftime('%Y-%m-%d')
                
                if self.is_trading_day(market, next_date_str):
                    logger.debug(f"[{date_str}] 下一个交易日: {next_date_str}")
                    return next_date_str
            
            # 找不到交易日，返回30天后
            logger.warning(f"[{date_str}] 未找到下一个交易日，返回30天后")
            fallback_date = (date + timedelta(days=30)).strftime('%Y-%m-%d')
            return fallback_date
            
        except Exception as e:
            logger.error(f"获取下一个交易日失败: {e}")
            return date_str
    
    def get_trading_days_between(
        self,
        market: Market,
        start_date: str,
        end_date: str
    ) -> list:
        """
        获取两个日期之间的所有交易日
        
        Args:
            market: 市场类型
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        
        Returns:
            list: 交易日列表
        """
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            
            trading_days = []
            current = start
            
            while current <= end:
                current_str = current.strftime('%Y-%m-%d')
                if self.is_trading_day(market, current_str):
                    trading_days.append(current_str)
                current += timedelta(days=1)
            
            logger.debug(f"[{start_date} ~ {end_date}] 交易日数量: {len(trading_days)}")
            return trading_days
            
        except Exception as e:
            logger.error(f"获取交易日列表失败: {e}")
            return []