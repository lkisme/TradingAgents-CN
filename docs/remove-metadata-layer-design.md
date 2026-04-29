# 设计：去掉 metadata 中间层，直接使用数据库统计

## 问题根因

### 当前架构

```
stock_daily_quotes（实际数据）→ cache_metadata（中间层）→ 判断逻辑
```

### 问题

1. **metadata 与实际数据不一致**
   - 凌晨同步时，数据源未更新，只同步到 2026-04-28
   - metadata 却标记 `last_sync_date = "2026-04-29"`
   - 16:30 判定"今天已同步"，全部跳过

2. **语义混淆**
   - `last_sync_date` 表示"今天执行了同步"
   - 而不是"数据已同步到今天"

3. **覆盖问题**
   - 增量同步时，只更新本次同步的数据范围
   - 盖了正确的历史范围（如 earliest_date）

---

## metadata 使用场景分析

| 文件 | 用途 | 影响 |
|------|------|------|
| `daily_quotes_sync_service.py` | 判断是否需要同步 | ✅ 主要场景 |
| `sina_kline_sync_service.py` | 新浪K线同步 | ⚠️ 需要同步修改 |
| `resilient_provider_enhanced.py` | 数据获取时的缓存检查 | ⚠️ 需要同步修改 |

---

## 设计方案

### 方案：去掉 metadata，直接统计数据库

```
stock_daily_quotes（实际数据）→ 聚合统计 → 判断逻辑
```

### 核心改动

#### 1. 删除 last_sync_date 判断逻辑

**当前代码**：
```python
# 检查是否已同步（跳过当天已同步的）
metadata = adapter.get_cache_metadata(symbol)
if metadata and metadata.get('last_sync_date') == today:
    results['skipped'] += 1
    continue
```

**改为**：
```python
# 检查数据库最新日期是否已是今天
actual_stats = adapter.get_historical_data_stats(symbol)
if actual_stats.get('latest_date') == today:
    results['skipped'] += 1
    logger.debug(f"⏭️ [{symbol}] 数据已是今天({today})，跳过")
    continue
```

#### 2. validate_cache_by_date_range 使用实际统计

**当前代码**：
```python
metadata = self.get_cache_metadata(symbol)
earliest_date = metadata.get('earliest_date')
latest_date = metadata.get('latest_date')
```

**改为**：
```python
actual_stats = self.get_historical_data_stats(symbol)
earliest_date = actual_stats.get('earliest_date')
latest_date = actual_stats.get('latest_date')
```

#### 3. 删除 update_cache_metadata 调用

不再维护 metadata，直接依赖数据库统计。

---

## 性能评估

### get_historical_data_stats 耗时

```
单只股票: ~0.33 秒
120 只股票: ~40 秒（可接受）
```

### 聚合查询

```javascript
db.stock_daily_quotes.aggregate([
    {$match: {code: "600928"}},
    {$group: {
        _id: null,
        earliest_date: {$min: "$trade_date"},
        latest_date: {$max: "$trade_date"},
        total_records: {$sum: 1}
    }}
])
```

---

## 修改范围

### daily_quotes_sync_service.py

| 行号 | 修改内容 |
|------|----------|
| 590-600 | 删除 last_sync_date 判断 |
| 700-710 | validate 使用 get_historical_data_stats |
| 800-820 | 删除 update_cache_metadata 调用 |

### enhanced_mongodb_adapter.py

| 行号 | 修改内容 |
|------|----------|
| 35-90 | validate_cache_by_date_range 使用实际统计 |
| 142-180 | 删除或改为可选 |

### sina_kline_sync_service.py

| 行号 | 修改内容 |
|------|----------|
| 198 | 改用数据库统计 |
| 313 | 删除 metadata 更新 |

### resilient_provider_enhanced.py

| 行号 | 修改内容 |
|------|----------|
| 77 | validate 使用实际统计 |
| 178 | 删除 metadata 更新 |

---

## 优点

1. **数据一致性**：metadata 与实际数据永远一致
2. **无语义混淆**：直接判断数据日期，不再依赖"执行标记"
3. **减少维护负担**：不再需要维护 metadata 集合
4. **解决凌晨问题**：凌晨同步没数据 → latest_date 不更新 → 16:30 会继续同步

---

## 缺点

1. **性能开销**：每次判断需要数据库聚合查询
2. **删除历史依赖**：metadata 可能有其他用途（需要确认）

---

## 待确认

1. cache_metadata 是否有其他用途？
2. 是否需要保留 metadata 作为缓存（性能优化）？
3. sina_kline_sync_service 是否需要同步修改？

---

---

## 可观测性要求

### 跳过原因必须输出日志

每个跳过条件都必须有明确的日志输出，方便排查问题。

#### daily_quotes_sync_service.py

```python
# 条件1：数据已是今天
actual_stats = adapter.get_historical_data_stats(symbol)
if actual_stats.get('latest_date') == today:
    logger.info(f"⏭️ [{symbol}] 数据已是今天({today})，跳过")
    results['skipped'] += 1
    continue

# 条件2：缓存完整（earliest <= 一年前 且 latest >= 今天）
is_complete, reason, _ = adapter.validate_cache_by_date_range(symbol)
if is_complete:
    logger.info(f"⏭️ [{symbol}] 缓存完整({reason})，跳过")
    results['skipped'] += 1
    continue

# 条件3：获取策略为 skip
strategy, fetch_start, fetch_end = adapter.get_fetch_strategy(symbol, actual_stats)
if strategy == 'skip':
    logger.info(f"⏭️ [{symbol}] 获取策略=skip，跳过")
    results['skipped'] += 1
    continue
```

#### resilient_provider_enhanced.py

```python
# 条件1：缓存完整
is_complete, reason = adapter.validate_cache_by_date_range(symbol)
if is_complete:
    logger.info(f"✅ [{symbol}] 缓存命中且完整({reason})")
    return cached_data

# 条件2：获取策略为 skip
strategy, fetch_start, fetch_end = adapter.get_fetch_strategy(symbol, actual_stats)
if strategy == 'skip':
    logger.info(f"⏭️ [{symbol}] 获取策略=skip，无数据")
```

#### sina_kline_sync_service.py

```python
# 条件1：数据已是今天
actual_latest = db.stock_daily_quotes.find_one({code: code}, sort=[('date', -1])
if actual_latest and actual_latest.get('date') == today:
    logger.info(f"⏭️ [{code}] 数据已是今天({today})，跳过")
    continue
```

---

## 实现顺序

| 序号 | 文件 | 修改内容 |
|------|------|----------|
| **1** | daily_quotes_sync_service.py | 删除 last_sync_date 判断 + 可观测性日志 |
| **2** | enhanced_mongodb_adapter.py | validate 使用实际统计 |
| **3** | resilient_provider_enhanced.py | 使用新的 validate 逻辑 |
| **4** | sina_kline_sync_service.py | 删除 metadata 判断 |
| **5** | 删除 cache_metadata 集合（可选） |

---

## 状态

- ✅ 设计完成（含可观测性）
- ⏳ 待实现