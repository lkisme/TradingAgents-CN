# 设计：上市日期验证方案（精确版）

## 问题

新股（上市不足一年）即使数据完整，也会被判定为"缓存不完整"。

---

## 设计方案

### 核心思路

如果 `earliest_date > one_year_ago`，则：
1. 获取股票上市日期
2. 比较 `earliest_date` 和上市日期
3. 如果一致（或接近），则认为缓存完整

---

## 数据源

### AKShare: `stock_ipo_summary_cninfo`

```python
import akshare as ak

ipo_info = ak.stock_ipo_summary_cninfo(symbol='603518')
# 返回字段包含：招股公告日期、上市日期等
```

---

## 实现设计

### 1. 新建获取上市日期函数

**文件**: `tradingagents/utils/stock_info_utils.py`

```python
#!/usr/bin/env python3
"""
股票信息工具
"""
import logging
from typing import Optional
from datetime import datetime

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
                        elif isinstance(listing_date, datetime):
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
```

---

### 2. 修改 validate_cache_by_date_range

**文件**: `tradingagents/dataflows/cache/enhanced_mongodb_adapter.py`

```python
def validate_cache_by_date_range(self, symbol: str) -> Tuple[bool, str, Optional[dict]]:
    """
    用日期范围验证缓存完整性
    
    🔥 改进：新股通过上市日期验证
    """
    
    stats = self.get_historical_data_stats(symbol)
    earliest_date = stats.get('earliest_date')
    latest_date = stats.get('latest_date')
    
    if not earliest_date or not latest_date:
        return False, "无数据或缺少日期范围", stats
    
    one_year_ago = TradingDayUtils.get_one_year_ago_trading_day()
    latest_closed_day = TradingDayUtils.get_latest_closed_trading_day()
    
    # === 判断完整性 ===
    
    # 1. 最新日期判断
    latest_valid = latest_date >= latest_closed_day
    
    # 2. 最早日期判断（改进）
    earliest_valid = False
    
    if earliest_date <= one_year_ago:
        # 老股，数据足够久
        earliest_valid = True
    else:
        # 新股，通过上市日期验证
        from tradingagents.utils.stock_info_utils import validate_new_stock_cache
        earliest_valid = validate_new_stock_cache(symbol, earliest_date)
    
    # === 返回结果 ===
    if earliest_valid and latest_valid:
        return True, "缓存完整", stats
    
    # === 分析不完整原因 ===
    reasons = []
    
    if not earliest_valid:
        # 新股检查上市日期
        from tradingagents.utils.stock_info_utils import get_listing_date
        listing_date = get_listing_date(symbol)
        if listing_date:
            reasons.append(f"起始不足（earliest={earliest_date}, listing={listing_date}）")
        else:
            reasons.append(f"起始不足（{earliest_date} > {one_year_ago}）")
    
    if not latest_valid:
        reasons.append(f"有Gap...")
    
    return False, "; ".join(reasons), stats
```

---

## 流程图

```
validate_cache_by_date_range(symbol)
    │
    ├─ earliest_date <= one_year_ago?
    │   ├─ Yes → earliest_valid = True（老股）
    │   └─ No → 新股验证流程：
    │       │
    │       ├─ 🔍 开始验证（INFO日志）
    │       │
    │       ├─ get_listing_date(symbol)
    │       │   ├─ 成功 → 📅 返回上市日期（INFO日志）
    │       │   └─ 失败 → ❌ 假设不完整（WARNING日志）
    │       │
    │       ├─ 📐 计算 delta（INFO日志）
    │       │
    │       ├─ 比较 earliest_date 和 listing_date
    │       │   ├─ delta <= 3天 → ✅ earliest_valid = True（INFO日志）
    │       │   └─ delta > 3天 → ❌ earliest_valid = False（WARNING日志）
    │
    └─ latest_date >= latest_closed?
        ├─ Yes → latest_valid = True
        └─ No → latest_valid = False
    
    earliest_valid AND latest_valid?
        ├─ Yes → 缓存完整 ✅
        └─ No → 缓存不完整 ❌
```

---

## 测试场景

| 场景 | earliest | listing_date | delta | earliest_valid | 结果 |
|------|----------|--------------|-------|----------------|------|
| **新股完整** | 2025-11-01 | 2025-11-03 | 2天 | True | ✅ 缓存完整 |
| **新股缺失** | 2025-12-01 | 2025-11-03 | 28天 | False | ❌ 起始不足 |
| **无上市日期** | 2025-11-01 | None | - | False | ❌ 假设不完整 |
| **老股完整** | 2022-02-07 | - | - | True | ✅ 缓存完整 |
| **边界1** | 2025-11-01 | 2025-11-04 | 3天 | True | ✅ delta=3刚好通过 |
| **边界2** | 2025-11-01 | 2025-11-05 | 4天 | False | ❌ delta=4超过容忍 |

---

## 日志输出要求

每个环节必须输出日志，便于排查：

| 环节 | 级别 | 内容 |
|------|------|------|
| 开始验证 | INFO | `🔍 [{symbol}] 开始新股缓存验证，earliest_date=...` |
| 获取上市日期成功 | INFO | `📅 [{symbol}] 上市日期=...` |
| 获取上市日期失败 | WARNING | `❌ [{symbol}] 无法获取上市日期，假设缓存不完整` |
| 计算delta | INFO | `📐 [{symbol}] delta=X天（earliest=..., listing=...）` |
| 判断完整 | INFO | `✅ [{symbol}] 新股缓存完整（delta=X天 <= 3天）` |
| 判断不完整 | WARNING | `❌ [{symbol}] 新股缓存不完整（delta=X天 > 3天）` |
| 解析失败 | ERROR | `❌ [{symbol}] 日期解析失败: ...` |

---

## 优点

1. **精确判断**：通过上市日期验证，不误判新股
2. **容错设计**：±3天误差容忍，避免数据源差异
3. **缓存优化**：上市日期只查询一次，缓存避免重复请求
4. **保守策略**：无法获取上市日期时假设不完整，触发手动补充
5. **可观测性**：每个环节都有日志输出，便于排查

---

## 性能考虑

| 操作 | 耗时 | 说明 |
|------|------|------|
| 内存缓存查询 | ~1ms | 上市日期缓存 |
| AKShare API | ~1-3s | 首次查询（新股） |
| 日期比较 | ~1ms | datetime 计算 |

**影响**：只有新股首次查询时会有延迟（约1-3秒），老股无影响。

---

## 修改范围

| 文件 | 修改 |
|------|------|
| `tradingagents/utils/stock_info_utils.py` | 新建上市日期查询函数 |
| `tradingagents/dataflows/cache/enhanced_mongodb_adapter.py` | 新股验证逻辑 |

---

## 状态

- ✅ 设计完成
- ⏳ 待实现