# TradingAgents-CN 数据源冗余设计文档

## 1. 问题背景

### 1.1 当前现象
- AKShare `stock_zh_a_hist()` 历史行情接口被东方财富100%限流
- 错误信息: `Connection aborted`, `Remote end closed connection`
- 市场分析师无法获取365天历史数据 → 技术指标(MA/MACD/KDJ/RSI)计算失败
- 分析报告生成受阻或质量下降

### 1.2 当前架构
```
┌─────────────────────────────────────────────────────────────┐
│                    Unified Tools Layer                       │
│  get_stock_market_data_unified / get_stock_fundamentals_... │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   Data Source Manager                        │
│  - 数据源优先级管理 (MongoDB configurable)                   │
│  - 降级逻辑 (_try_fallback_sources)                         │
│  - 质量检查与重试                                            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────┐    ┌──────────────────┐
│  AKShareProvider │    │ BaoStockProvider │
│  - 历史行情      │    │ - 历史行情       │
│  - 财务数据      │    │ - 财务数据       │
│  - 新闻数据      │    │ - 股票列表       │
│  - 股票列表      │    │                  │
└──────────────────┘    ┌──────────────────┘
```

### 1.3 降级缺口分析
- **Provider层**: 各Provider独立，无自动切换机制
- **Manager层**: 有 `_try_fallback_sources()` 但调用时机不确定
- **Tool层**: 部分有fallback，但不覆盖所有场景

## 2. 需求目标

**核心目标**: AKShare 失败时自动切换 BaoStock，BaoStock 也失败才报错

**验收标准**:
1. AKShare限流期间，分析任务仍能完成
2. 数据一致性：BaoStock返回数据格式与AKShare一致
3. 清晰日志：记录切换过程，便于排查
4. 可配置：数据源优先级可通过MongoDB调整

## 3. 实现范围

### Phase 1: 历史行情冗余 (P0 - 最高优先级)
- 覆盖 `get_historical_data()` 方法
- 市场分析师核心依赖
- BaoStock有对应API `query_history_k_data_plus()`

### Phase 2: 财务数据冗余 (P1)
- 覆盖财务数据获取
- 基本面分析师依赖
- BaoStock有业绩快报API

### Phase 3: 实时行情/新闻 (P2 - 需评估)
- BaoStock无直接对应API
- 可能需要引入其他数据源(Tushare)

## 4. 技术方案

### 4.1 方案选择: Provider层封装

新建 `ResilientChinaStockProvider` 类，封装AKShare和BaoStock，提供统一接口。

**理由**:
- 不修改现有Provider，保持向后兼容
- 清晰的降级逻辑，易于维护
- 可独立测试和扩展

### 4.2 类设计

```python
class ResilientChinaStockProvider(BaseStockDataProvider):
    """带冗余的中国股票数据提供器"""
    
    def __init__(self):
        super().__init__("resilient_china")
        self.akshare = AKShareProvider()
        self.baostock = BaoStockProvider()
        self._source_priority = ["akshare", "baostock"]  # 可配置
    
    async def get_historical_data(self, code, start_date, end_date, period="daily"):
        """
        获取历史行情数据，带自动降级
        
        流程:
        1. 尝试 AKShare
        2. AKShare失败 → 切换 BaoStock
        3. BaoStock失败 → 返回None或抛异常
        """
        for source_name in self._source_priority:
            provider = self._get_provider(source_name)
            
            try:
                df = await provider.get_historical_data(code, start_date, end_date, period)
                if df and not df.empty:
                    self._current_source = source_name
                    logger.info(f"✅ [{source_name}] 历史数据获取成功: {code}")
                    return df
            except Exception as e:
                logger.warning(f"⚠️ [{source_name}] 历史数据获取失败: {e}")
                continue
        
        logger.error(f"❌ 所有数据源均失败: {code}")
        return None
```

### 4.3 数据格式标准化

**AKShare列名** (stock_zh_a_hist):
```
日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 暂跌幅, 暂跌额, 换手率
```

**BaoStock列名** (query_history_k_data_plus):
```
date, code, open, high, low, close, volume, amount, adjustflag, turn, tradestatus
```

**标准化后**:
```
date, open, close, high, low, volume, amount, turnover, change_percent
```

### 4.4 股票代码转换

| Provider | 输入格式 | 输出格式 |
|----------|----------|----------|
| AKShare | `600519` | `600519` |
| BaoStock | `600519` | `sh.600519` |

转换逻辑:
```python
def _format_code_for_baostock(code: str) -> str:
    """将纯代码转换为BaoStock格式"""
    if code.startswith(('sh', 'sz', 'bj')):
        return code
    
    # 根据代码规则判断市场
    if code.startswith(('6', '900', '688')):
        return f"sh.{code}"
    elif code.startswith(('0', '2', '3', '003', '002')):
        return f"sz.{code}"
    elif code.startswith(('8', '4')):
        return f"bj.{code}"
    else:
        return f"sh.{code}"  # 默认上海
```

### 4.5 BaoStock连接管理

```python
class BaoStockProvider:
    async def get_historical_data(self, code, start_date, end_date, period="daily"):
        # 登录
        lg = self.bs.login()
        if lg.error_code != '0':
            raise ConnectionError(f"BaoStock登录失败: {lg.error_msg}")
        
        try:
            # 格式化代码和日期
            bs_code = self._format_code(code)
            bs_start = start_date.replace('-', '')
            bs_end = end_date.replace('-', '')
            
            # 查询
            rs = self.bs.query_history_k_data_plus(
                bs_code,
                fields="date,code,open,high,low,close,volume,amount,turn",
                start_date=bs_start,
                end_date=bs_end,
                frequency="d",
                adjustflag="2"  # 前复权
            )
            
            # 处理结果...
        finally:
            self.bs.logout()  # 必须logout
```

## 5. 集成点

### 5.1 修改 Data Source Manager

在 `data_source_manager.py` 中使用新的 Resilient Provider:

```python
# 原代码
self._providers[DataSourceCode.AKSHARE] = AKShareProvider()

# 修改为
self._providers[DataSourceCode.RESILIENT_CHINA] = ResilientChinaStockProvider()
self.set_current_source(DataSourceCode.RESILIENT_CHINA)
```

### 5.2 或: 在 Unified Tool 层处理

在 `get_stock_market_data_unified` 工具中调用:

```python
async def get_stock_market_data_unified(symbol: str, ...):
    # 使用 Resilient Provider
    provider = ResilientChinaStockProvider()
    df = await provider.get_historical_data(symbol, start_date, end_date)
    ...
```

## 6. 测试计划

### 6.1 单元测试
```python
def test_fallback_to_baostock():
    """AKShare失败时自动切换BaoStock"""
    provider = ResilientChinaStockProvider()
    
    # Mock AKShare失败
    provider.akshare.connected = False
    
    df = await provider.get_historical_data("600519", "2025-01-01", "2025-12-31")
    
    assert df is not None
    assert provider._current_source == "baostock"

def test_all_sources_fail():
    """所有数据源失败时返回None"""
    provider = ResilientChinaStockProvider()
    
    # Mock全部失败
    provider.akshare.connected = False
    provider.baostock.connected = False
    
    df = await provider.get_historical_data("600519", ...)
    
    assert df is None
```

### 6.2 集成测试
- 在容器内测试限流场景
- 对比AKShare和BaoStock数据一致性
- 验证分析任务在限流期间能否完成

## 7. 文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `tradingagents/dataflows/providers/china/resilient_provider.py` | 新建：ResilientChinaStockProvider类 |
| `tradingagents/dataflows/providers/china/__init__.py` | 添加导出 |
| `tradingagents/dataflows/providers/china/baostock.py` | 增强：连接管理、数据格式标准化 |
| `tradingagents/dataflows/data_source_manager.py` | 集成：使用Resilient Provider |
| `tradingagents/dataflows/tools/market_data.py` | 可能修改：调用方式 |

## 8. 非功能性需求

| 需求 | 说明 |
|------|------|
| 性能 | 降级切换增加延迟应<3秒 |
| 日志 | 记录数据源切换、耗时、失败原因 |
| 可配置 | 优先级可通过MongoDB调整 |
| 可扩展 | 未来可加入Tushare等 |
| 向后兼容 | 不破坏现有功能 |

## 9. 验收清单

- [ ] ResilientChinaStockProvider类实现完成
- [ ] 历史行情获取带自动降级
- [ ] 数据格式标准化正确
- [ ] 日志记录清晰完整
- [ ] 单元测试通过
- [ ] 集成测试通过
- [ ] 部署后分析任务正常运行
- [ ] 限流场景模拟测试通过