# MongoDB 缓存优先方案设计文档

> 版本: v4 (最终版)
> 日期: 2026-04-16
> 状态: 待实施

---

## 一、决策汇总

| 问题 | 最终决策 |
|------|---------|
| **完整性判断** | 日期范围：earliest ≤ 一年前，latest ≥ 最近交易日 |
| **一年定义** | 365 天日期范围（约 250 交易日） |
| **Gap 补全策略** | 收盘后 gap > 7 天 → 全量请求补全 |
| **盘中补当日** | **不补**，等收盘后再补 |
| **定时同步** | 16:30, Top 120 + 持仓, 一年交易日 |
| **API 全失败** | **终止分析** |
| **缓存不完整** | **强制补全**后再分析 |
| **cache_metadata** | **新建集合** |
| **Tushare Token** | **暂不处理** |

---

## 二、背景与问题

### 2.1 当前问题

| 失败类型 | 具体错误 | 频率 | 根因 |
|---------|---------|------|------|
| **AKShare 连接断开** | `RemoteDisconnected` | 🔴 高 | API 不稳定，并发请求时易断连 |
| **BaoStock 网络错误** | `网络接收错误` | 🔴 高 | 服务器不稳定 |
| **Tushare Token 无效** | `token不对` | 🔴 高 | api_key 长度为 0 |
| **MongoDB 缓存未利用** | 38877 条日线数据未作为优先数据源 | 🔴 高 | 当前优先级是 API → MongoDB |

### 2.2 MongoDB 缓存现状

| 集合 | 文档数 | 最新日期 | 问题 |
|------|-------|---------|------|
| `stock_daily_quotes` | 38877 | 2026-04-10 | Gap 6 天，未被利用 |
| `stock_financial_data` | 2 | - | 几乎无数据 |
| `market_quotes` | 5841 | - | 实时行情正常 |

---

## 三、数据流程图

### 3.1 分析任务请求日线数据

```
分析任务请求日线数据（一年交易日）
           ↓
检查 MongoDB 缓存 + cache_metadata
           ↓
┌──────────────────────────────────────────┐
│  用日期范围验证完整性                        │
│  ├─ earliest_date ≤ 一年前交易日？          │
│  ├─ latest_date ≥ 最近已收盘交易日？        │
│  ├─ 两条件都满足 → ✅ 缓存完整，直接返回      │
│  └────────────────────────────────────┤
│  不完整 → 判断补全策略                       │
│  ├─ 盘中 → 调用 API（不补当日）              │
│  ├─ 收盘后 + Gap ≤ 7天 → API增量补          │
│  ├─ 收盘后 + Gap > 7天 → API全量获取        │
│  ├─ 起始不足 → API全量获取                  │
│  └────────────────────────────────────┤
│  API 获取                                  │
│  ├─ AKShare（失败重试）                     │
│  ├─ BaoStock（备用）                        │
│  ├─ 成功 → 写入缓存 → 返回数据               │
│  ├─ 全失败 → ❌ 抛出异常，终止分析            │
└──────────────────────────────────────────┘
```

### 3.2 定时同步日线数据

```
每日 16:30 定时任务触发
           ↓
检查是否收盘后（15:00 之后）
           ↓
获取股票池（Top 120 + 持仓）
           ↓
对每只股票：
  ├─ 检查 cache_metadata（跳过已同步）
  ├─ 获取一年交易日（365天前 → 今天）
  ├─ AKShare API 获取日线
  ├─ 写入 stock_daily_quotes（upsert）
  ├─ 更新 cache_metadata（earliest/latest）
  └──────────────────────────────────┤
  失败 → 标记 is_complete=false
           ↓
同步完成报告
```

---

## 四、MongoDB 集合设计

### 4.1 新增 cache_metadata 集合

```javascript
// 创建集合和索引
db.createCollection("cache_metadata")
db.cache_metadata.createIndex({ symbol: 1, collection: 1 }, { unique: true })
db.cache_metadata.createIndex({ last_sync_date: 1 })
```

**文档结构**：

```json
{
  "_id": ObjectId("..."),
  "symbol": "600036",
  "collection": "stock_daily_quotes",
  "earliest_date": "2025-04-15",
  "latest_date": "2026-04-15",
  "total_records": 250,
  "is_complete": true,
  "last_sync_date": "2026-04-16",
  "data_source": "akshare",
  "updated_at": ISODate("2026-04-16T16:30:00Z")
}
```

### 4.2 stock_daily_quotes 索引优化

```javascript
db.stock_daily_quotes.createIndex({ symbol: 1, trade_date: -1 })
db.stock_daily_quotes.createIndex({ trade_date: -1 })
```

---

## 五、核心判断逻辑

### 5.1 缓存完整性验证

**判断条件**：
- `earliest_date ≤ 一年前交易日`
- `latest_date ≥ 最近已收盘交易日`

**示例（今天 2026-04-16）**：

| 缓存 earliest | 缓存 latest | 一年前 | 最近交易日 | 判断 |
|--------------|-------------|--------|-----------|------|
| 2025-04-15 | 2026-04-15 | 2025-04-15 | 2026-04-15 | ✅ 完整 |
| 2025-05-01 | 2026-04-15 | 2025-04-15 | 2026-04-15 | ❌ 起始不足 |
| 2025-04-15 | 2026-04-10 | 2025-04-15 | 2026-04-15 | ❌ 有 Gap 5天 |
| 2025-05-01 | 2026-04-10 | 2025-04-15 | 2026-04-15 | ❌ 双重不足 |

### 5.2 最近已收盘交易日判断

| 场景 | 时间 | 最近已收盘交易日 |
|------|------|-----------------|
| **交易日盘中** | 09:30-15:00 | 上一个交易日 |
| **交易日收盘后** | 15:00 之后 | 今天 |
| **非交易日** | 周末/节假日 | 上一个交易日 |

### 5.3 数据获取策略

| 场景 | 策略 | 说明 |
|------|------|------|
| **无缓存** | full | 全量获取（一年前 → 最近交易日） |
| **起始不足** | full | 全量获取 |
| **盘中 + latest ≥ yesterday** | skip | 缓存有效，跳过 |
| **盘中 + latest < yesterday** | gap | 补到昨日（不补当日） |
| **收盘后 + Gap ≤ 7天** | incremental | 增量补 |
| **收盘后 + Gap > 7天** | full | 全量获取 |
| **缓存完整** | skip | 跳过 |

---

## 六、文件改动清单

| 步骤 | 内容 | 文件位置 | 优先级 |
|------|------|---------|--------|
| **1** | 创建 cache_metadata 集合和索引 | MongoDB | P0 |
| **2** | 创建 TradingDayUtils 工具类 | `tradingagents/utils/trading_day_utils.py` | P0 |
| **3** | 创建 EnhancedMongoDBCacheAdapter | `tradingagents/dataflows/cache/enhanced_mongodb_adapter.py` | P0 |
| **4** | 创建 ResilientChinaStockProviderEnhanced | `tradingagents/dataflows/providers/china/resilient_provider.py` | P0 |
| **5** | 修改 data_source_manager 调用新 Provider | `tradingagents/dataflows/data_source_manager.py` | P0 |
| **6** | 创建 DailyQuotesSyncService | `app/services/daily_quotes_sync_service.py` | P1 |
| **7** | 创建股票池获取函数 | `app/services/stock_pool_service.py` | P1 |
| **8** | 配置定时同步任务 | `app/routers/scheduler.py` | P1 |
| **9** | 单元测试 | `tests/` | P2 |

---

## 七、预期效果

| 场景 | 当前行为 | 改进后行为 |
|------|---------|-----------|
| **缓存完整** | 不检查，每次调用 API | 日期范围验证 → 直接返回缓存 |
| **起始不足** | 数据不完整 | 判断 earliest > 一年前 → 全量获取 |
| **有 Gap ≤ 7天** | 数据不完整 | 增量补全 + 合并 |
| **有 Gap > 7天** | 数据不完整 | 全量获取 |
| **盘中请求** | 调用 API | 缓存验证 → API（不补当日） |
| **API 全失败** | ❌ 终止分析 | ❌ 抛出 DataFetchError |
| **定时同步** | 无 | 每日 16:30 同步股票池 |

---

## 八、附录：核心代码示例

详见实施文档，主要包含：

1. `TradingDayUtils` - 交易日判断工具类
2. `EnhancedMongoDBCacheAdapter` - MongoDB 缓存适配器（日期范围验证）
3. `ResilientChinaStockProviderEnhanced` - Resilient Provider（缓存优先）
4. `DailyQuotesSyncService` - 定时同步服务

---

## 九、实施进度

| 状态 | 说明 |
|------|------|
| ⏳ 待实施 | 方案设计完成，等待实施 |