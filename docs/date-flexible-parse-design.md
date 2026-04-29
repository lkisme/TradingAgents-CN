# 设计：日期格式灵活解析方案

## 问题

AKShare 写入的 trade_date 字段可能带时间部分：
- `"2026-04-28"` (纯日期)
- `"2026-04-28 00:00:00"` (带时间)
- `"2026/04/28"` (其他格式)

导致 strptime 解析失败。

---

## 方法2：灵活解析方案

### 设计思路

创建统一的日期解析函数，支持多种格式，一处修改全局生效。

---

### 核心实现

#### 1. 创建日期解析工具函数

**文件**: `tradingagents/utils/date_utils.py` (新建)

```python
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
```

---

#### 2. 修改 daily_quotes_sync_service.py

**位置**: 第 628-630 行

```python
# 当前代码
gap_days = (dt.strptime(latest_closed, '%Y-%m-%d') - 
           dt.strptime(actual_latest, '%Y-%m-%d')).days

# 改为
from tradingagents.utils.date_utils import parse_trade_date
latest_dt = parse_trade_date(latest_closed)
actual_dt = parse_trade_date(actual_latest)
if latest_dt and actual_dt:
    gap_days = (latest_dt - actual_dt).days
else:
    gap_days = 0  # 解析失败，跳过判断
```

---

#### 3. 修改 enhanced_mongodb_adapter.py

**位置**: validate_cache_by_date_range 函数

```python
# 当前代码
earliest_valid = earliest_date <= one_year_ago
latest_valid = latest_date >= latest_closed_day

# 改为
from tradingagents.utils.date_utils import parse_trade_date_str
earliest_norm = parse_trade_date_str(earliest_date)
latest_norm = parse_trade_date_str(latest_date)
earliest_valid = earliest_norm <= one_year_ago
latest_valid = latest_norm >= latest_closed_day
```

---

#### 4. 修改 resilient_provider_enhanced.py

**位置**: Gap 计算部分

```python
# 当前代码
gap_days = (dt.strptime(latest_closed, '%Y-%m-%d') - 
           dt.strptime(latest, '%Y-%m-%d')).days

# 改为
from tradingagents.utils.date_utils import parse_trade_date
latest_dt = parse_trade_date(latest_closed)
actual_dt = parse_trade_date(latest)
if latest_dt and actual_dt:
    gap_days = (latest_dt - actual_dt).days
else:
    gap_days = 0
```

---

### 测试场景

| 输入 | 输出 | 说明 |
|------|------|------|
| `"2026-04-28"` | `"2026-04-28"` | ✅ 标准格式 |
| `"2026-04-28 00:00:00"` | `"2026-04-28"` | ✅ 清理时间 |
| `"2026/04/28"` | `"2026-04-28"` | ✅ 斜杠格式 |
| `"20260428"` | `"2026-04-28"` | ✅ 无分隔符 |
| `None` | `None` | ✅ 空值处理 |
| `"invalid"` | `"invalid"` | ⚠️ 无法解析，返回原值 |

---

### 边界情况处理

1. **空值**: 返回 None 或原值，不抛异常
2. **无法解析**: 记录 warning 日志，返回清理后的值
3. **未来写入错误**: 自动兼容，不会导致任务失败

---

### 优点

| 优点 | 说明 |
|------|------|
| **一处修改** | 统一函数，所有代码调用 |
| **多种格式** | 支持常见日期格式 |
| **防御性** | 新数据源写入也不会失败 |
| **可观测** | 解析失败有日志 |

---

### 缺点

| 缺点 | 说明 |
|------|------|
| **依赖引入** | 所有文件需导入 date_utils |
| **性能** | 多次尝试解析（影响很小） |

---

### 实现优先级

| 优先级 | 任务 |
|--------|------|
| **P0** | 创建 date_utils.py |
| **P0** | 修改 daily_quotes_sync_service.py |
| **P0** | 修改 enhanced_mongodb_adapter.py |
| **P0** | 修改 resilient_provider_enhanced.py |
| **P1** | 清理已有数据（可选） |

---

## 状态

- ✅ 设计完成
- ⏳ 待实现