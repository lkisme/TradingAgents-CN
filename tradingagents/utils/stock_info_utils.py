#!/usr/bin/env python3
"""
股票信息工具
"""
import logging
from typing import Optional
from datetime import datetime, date

logger = logging.getLogger(__name__)

# 上市日期缓存（避免重复查询）
_listing_date_cache = {}


def get_listing_date(symbol: str) -> Optional[str]:
    """
    获取股票上市日期
    
    Args:
        symbol: 6位股票代码
        
    Returns:
        上市日期字符串 (YYYY-MM-DD)，失败返回 None
    """
    # 检查缓存
    if symbol in _listing_date_cache:
        return _listing_date_cache[symbol]
    
    try:
        import akshare as ak
        
        # 使用 IPO 信息接口
        ipo_info = ak.stock_ipo_summary_cninfo(symbol=symbol)
        
        if ipo_info is not None and len(ipo_info) > 0:
            # 查找上市日期字段
            for col in ipo_info.columns:
                if '上市' in col or '挂牌' in col:
                    listing_date = ipo_info[col].values[0]
                    if listing_date:
                        # 标准化日期格式
                        if isinstance(listing_date, str):
                            clean_date = listing_date.split(' ')[0]
                            _listing_date_cache[symbol] = clean_date
                            return clean_date
                        elif isinstance(listing_date, (datetime, date)):
                            clean_date = listing_date.strftime('%Y-%m-%d')
                            _listing_date_cache[symbol] = clean_date
                            return clean_date
        
        logger.warning(f"未找到 {symbol} 上市日期")
        return None
        
    except Exception as e:
        logger.warning(f"获取 {symbol} 上市日期失败: {str(e)[:50]}")
        return None


def is_new_stock(symbol: str, earliest_date: str, one_year_ago: str) -> bool:
    """
    判断是否为新股（上市不足一年）
    
    Args:
        symbol: 股票代码
        earliest_date: 数据最早日期
        one_year_ago: 一年前的日期
        
    Returns:
        是否为新股
    """
    return earliest_date > one_year_ago


def validate_new_stock_cache(symbol: str, earliest_date: str) -> bool:
    """
    验证新股缓存完整性
    
    如果 earliest_date 与上市日期一致（±3天），则认为缓存完整
    
    Args:
        symbol: 股票代码
        earliest_date: 数据最早日期
        
    Returns:
        缓存是否完整
    """
    logger.info(f"🔍 [{symbol}] 开始新股缓存验证，earliest_date={earliest_date}")
    
    listing_date = get_listing_date(symbol)
    
    if not listing_date:
        # 无法获取上市日期，假设不完整
        logger.warning(f"❌ [{symbol}] 无法获取上市日期，假设缓存不完整")
        return False
    
    logger.info(f"📅 [{symbol}] 上市日期={listing_date}")
    
    # 比较日期（允许 ±3 天误差）
    try:
        earliest_dt = datetime.strptime(earliest_date.split(' ')[0], '%Y-%m-%d')
        listing_dt = datetime.strptime(listing_date, '%Y-%m-%d')
        
        delta_days = abs((earliest_dt - listing_dt).days)
        logger.info(f"📐 [{symbol}] delta={delta_days}天（earliest={earliest_date}, listing={listing_date}）")
        
        if delta_days <= 3:
            logger.info(f"✅ [{symbol}] 新股缓存完整（delta={delta_days}天 <= 3天）")
            return True
        else:
            logger.warning(f"❌ [{symbol}] 新股缓存不完整（delta={delta_days}天 > 3天）")
            return False
            
    except Exception as e:
        logger.error(f"❌ [{symbol}] 日期解析失败: {e}")
        return False  # 解析失败，假设不完整