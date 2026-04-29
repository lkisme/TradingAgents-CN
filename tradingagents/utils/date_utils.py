#!/usr/bin/env python3
"""
日期解析工具
支持多种日期格式的统一解析
"""
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def normalize_trade_date(date_str: str) -> str:
    """
    标准化交易日日期格式
    
    Args:
        date_str: 原始日期字符串
        
    Returns:
        标准化后的日期字符串 (YYYY-MM-DD)
    """
    if not date_str:
        return date_str
    
    # 清理时间部分（常见格式）
    # "2026-04-28 00:00:00" -> "2026-04-28"
    if ' ' in date_str:
        date_str = date_str.split(' ')[0]
    
    return date_str


def parse_trade_date(date_str: str) -> Optional[datetime]:
    """
    解析交易日日期
    
    支持格式：
    - YYYY-MM-DD
    - YYYY-MM-DD HH:MM:SS
    - YYYY/MM/DD
    - YYYYMMDD
    
    Args:
        date_str: 日期字符串
        
    Returns:
        datetime 对象，失败返回 None
    """
    if not date_str:
        return None
    
    # 先标准化（去掉时间部分）
    date_clean = normalize_trade_date(date_str)
    
    # 尝试解析
    formats = [
        '%Y-%m-%d',      # 2026-04-28
        '%Y/%m/%d',      # 2026/04/28
        '%Y%m%d',        # 20260428
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_clean, fmt)
        except ValueError:
            continue
    
    logger.warning(f"无法解析日期: {date_str}")
    return None


def parse_trade_date_str(date_str: str) -> str:
    """
    解析并返回标准化日期字符串
    
    Args:
        date_str: 原始日期字符串
        
    Returns:
        YYYY-MM-DD 格式的字符串，失败返回原值
    """
    dt = parse_trade_date(date_str)
    if dt:
        return dt.strftime('%Y-%m-%d')
    return normalize_trade_date(date_str)  # 返回清理后的值