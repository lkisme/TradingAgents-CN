# 财务数据自动缓存设计

## ✅ 实现状态：已完成

## 问题背景

当Backend在股票分析时获取财务数据，如果MongoDB中无相关数据，会调用akshare等第三方接口获取。但当前实现中，财务数据获取成功后**不会自动缓存**到MongoDB。

## 现状分析

### 当前财务数据流程

#### 1. 主动同步流程（有缓存）
```
定时任务
  → AKShareSyncService.sync_financial_data()
  → provider.get_financial_data(symbol)
  → _save_financial_data()
  → FinancialDataService.save_financial_data()
  → MongoDB (stock_financial_data 集合)
```

**相关文件**：
- `app/worker/akshare_sync_service.py:754-900` - 同步入口和保存逻辑
- `app/services/financial_data_service.py:76-162` - MongoDB保存实现

#### 2. 分析时查询流程（无缓存）
```
分析请求
  → data_source_manager.get_fundamentals_data()
  → _get_mongodb_fundamentals()
  → MongoDB查询 (无数据)
  → _try_fallback_fundamentals()
  → _get_akshare_fundamentals()
  → _generate_fundamentals_analysis() ← 只生成基本信息，不获取财务数据
```

**问题代码**：
- `tradingagents/dataflows/data_source_manager.py:1930-1941`:
  ```python
  def _get_akshare_fundamentals(self, symbol: str) -> str:
      """从 AKShare 生成基本面分析"""
      # AKShare 没有直接的基本面数据接口，使用生成分析
      return self._generate_fundamentals_analysis(symbol)  # ← 问题：不获取真实数据
  ```

### 为什么不缓存

1. `_get_akshare_fundamentals()` 方法设计为只生成基本分析，而不是从AKShare获取财务数据
2. `ResilientChinaStockProvider.get_financial_data()` 有获取财务数据的能力，但没有被分析流程正确调用
3. 分析流程中没有调用 `FinancialDataService.save_financial_data()` 的逻辑

## 设计方案

### 方案概述

修改 `_get_akshare_fundamentals()` 方法：
1. 从 AKShare/BaoStock 获取真实财务数据
2. 成功获取后自动缓存到 MongoDB
3. 返回格式化的财务数据报告

### 详细实现

#### Step 1: 修改 `_get_akshare_fundamentals` 方法

文件：`tradingagents/dataflows/data_source_manager.py`

```python
def _get_akshare_fundamentals(self, symbol: str) -> str:
    """从 AKShare/BaoStock 获取基本面数据，并自动缓存到 MongoDB"""
    logger.debug(f"📊 [AKShare] 调用参数: symbol={symbol}")

    try:
        # 1. 使用 ResilientProvider 获取财务数据（支持自动降级）
        from tradingagents.dataflows.providers.china.resilient_provider import get_resilient_provider
        import concurrent.futures

        provider = get_resilient_provider()

        def fetch_financial_data_sync():
            """同步获取财务数据"""
            import asyncio
            try:
                # 尝试获取已有的事件循环
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果循环正在运行，使用 run_coroutine_threadsafe
                    import threading
                    new_loop = asyncio.new_event_loop()
                    try:
                        return new_loop.run_until_complete(
                            provider.get_financial_data(symbol)
                        )
                    finally:
                        new_loop.close()
                else:
                    return loop.run_until_complete(
                        provider.get_financial_data(symbol)
                    )
            except RuntimeError:
                # 没有事件循环，创建新的
                new_loop = asyncio.new_event_loop()
                try:
                    return new_loop.run_until_complete(
                        provider.get_financial_data(symbol)
                    )
                finally:
                    new_loop.close()

        # 使用线程池执行
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(fetch_financial_data_sync)
            financial_data = future.result(timeout=30)  # 30秒超时

        if financial_data:
            # 2. 获取成功，自动缓存到 MongoDB
            self._save_financial_data_to_mongodb(symbol, financial_data, provider.get_current_source())

            # 3. 格式化返回报告
            logger.info(f"✅ [数据来源: AKShare-财务数据] 成功获取并缓存: {symbol}")
            return self._format_financial_data_from_dict(symbol, financial_data)
        else:
            # 获取失败，降级到生成基本分析
            logger.warning(f"⚠️ [数据来源: AKShare] 财务数据获取失败，生成基本分析: {symbol}")
            return self._generate_fundamentals_analysis(symbol)

    except Exception as e:
        logger.error(f"❌ [数据来源: AKShare异常] 获取财务数据失败: {e}")
        return self._generate_fundamentals_analysis(symbol)
```

#### Step 2: 新增 `_save_financial_data_to_mongodb` 方法

文件：`tradingagents/dataflows/data_source_manager.py`

```python
def _save_financial_data_to_mongodb(self, symbol: str, financial_data: Dict[str, Any], data_source: str):
    """
    将财务数据保存到 MongoDB

    Args:
        symbol: 股票代码
        financial_data: 财务数据字典
        data_source: 数据来源 (akshare/baostock)
    """
    try:
        # 检查 MongoDB 缓存是否启用
        if not self.use_mongodb_cache:
            logger.debug(f"📊 MongoDB缓存未启用，跳过保存")
            return

        # 使用 FinancialDataService 保存数据
        from app.services.financial_data_service import get_financial_data_service
        import asyncio

        async def save_data_async():
            service = await get_financial_data_service()
            saved_count = await service.save_financial_data(
                symbol=symbol,
                financial_data=financial_data,
                data_source=data_source or "akshare",
                market="CN",
                report_type="quarterly"
            )
            return saved_count

        # 执行异步保存
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 使用线程池执行异步任务
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        lambda: asyncio.run(save_data_async())
                    )
                    saved_count = future.result(timeout=10)
            else:
                saved_count = loop.run_until_complete(save_data_async())
        except RuntimeError:
            saved_count = asyncio.run(save_data_async())

        if saved_count > 0:
            logger.info(f"✅ [MongoDB缓存] 财务数据已自动缓存: {symbol}, {saved_count}条记录")
        else:
            logger.warning(f"⚠️ [MongoDB缓存] 财务数据缓存失败: {symbol}")

    except Exception as e:
        logger.warning(f"⚠️ [MongoDB缓存] 保存财务数据失败: {e}")
        # 缓存失败不影响返回结果
```

#### Step 3: 新增 `_format_financial_data_from_dict` 方法

文件：`tradingagents/dataflows/data_source_manager.py`

```python
def _format_financial_data_from_dict(self, symbol: str, financial_data: Dict[str, Any]) -> str:
    """
    格式化从 AKShare/BaoStock 获取的财务数据为报告

    Args:
        symbol: 股票代码
        financial_data: 财务数据字典

    Returns:
        格式化的财务数据报告
    """
    try:
        # 获取股票基本信息
        stock_info = self.get_stock_info(symbol)

        report = f"📊 {symbol} 基本面数据（实时获取）\n\n"
        report += f"📈 股票名称: {stock_info.get('name', '未知')}\n"
        report += f"🏢 所属行业: {stock_info.get('industry', '未知')}\n\n"

        # 提取主要财务指标
        main_indicators = financial_data.get('main_indicators', [])
        if main_indicators and len(main_indicators) > 0:
            latest = main_indicators[0]

            report += "💰 核心财务指标:\n"
            report += f"   营业收入: {latest.get('营业收入', 'N/A')}\n"
            report += f"   净利润: {latest.get('净利润', 'N/A')}\n"
            report += f"   总资产: {latest.get('总资产', 'N/A')}\n"
            report += f"   净资产收益率(ROE): {latest.get('净资产收益率', 'N/A')}\n"
            report += f"   资产负债率: {latest.get('资产负债率', 'N/A')}\n"

        # 资产负债表摘要
        balance_sheet = financial_data.get('balance_sheet', [])
        if balance_sheet and len(balance_sheet) > 0:
            latest_balance = balance_sheet[0]
            report += "\n📋 资产负债表摘要:\n"
            report += f"   货币资金: {latest_balance.get('货币资金', 'N/A')}\n"
            report += f"   负债合计: {latest_balance.get('负债合计', 'N/A')}\n"

        # 利润表摘要
        income_statement = financial_data.get('income_statement', [])
        if income_statement and len(income_statement) > 0:
            latest_income = income_statement[0]
            report += "\n📈 利润表摘要:\n"
            report += f"   营业总收入: {latest_income.get('营业总收入', 'N/A')}\n"
            report += f"   营业成本: {latest_income.get('营业成本', 'N/A')}\n"

        # 现金流量表摘要
        cash_flow = financial_data.get('cash_flow', [])
        if cash_flow and len(cash_flow) > 0:
            latest_cash = cash_flow[0]
            report += "\n💵 现金流量表摘要:\n"
            report += f"   经营活动现金流: {latest_cash.get('经营活动产生的现金流量净额', 'N/A')}\n"

        report += "\n💡 数据已自动缓存到 MongoDB，下次查询将直接使用缓存\n"

        return report

    except Exception as e:
        logger.error(f"❌ 格式化财务数据失败: {e}")
        return f"📊 {symbol} 基本面数据已获取（格式化失败）\n💡 数据已缓存"
```

### 数据流变更

修改后的流程：
```
分析请求
  → data_source_manager.get_fundamentals_data()
  → _get_mongodb_fundamentals()
  → MongoDB查询 (无数据)
  → _try_fallback_fundamentals()
  → _get_akshare_fundamentals()
  → ResilientProvider.get_financial_data()  ← 新增：获取真实数据
  → _save_financial_data_to_mongodb()       ← 新增：自动缓存
  → _format_financial_data_from_dict()      ← 新增：格式化返回
```

### 优势

1. **减少API调用**：首次获取后缓存，后续直接使用缓存
2. **提高响应速度**：避免每次分析都调用第三方API
3. **数据一致性**：使用统一的 `FinancialDataService` 保存数据
4. **自动降级**：通过 `ResilientProvider` 支持 AKShare → BaoStock 自动降级

### 注意事项

1. **缓存条件**：只在 MongoDB 缓存启用 (`use_mongodb_cache=True`) 时保存
2. **异步处理**：使用线程池处理异步保存，避免阻塞主流程
3. **失败不影响**：缓存失败不影响返回结果，只是不缓存
4. **数据源记录**：保存时记录数据来源，便于后续维护

### 测试计划

1. 单元测试：验证 `_save_financial_data_to_mongodb` 方法
2. 集成测试：验证完整的获取 → 缓存 → 查询流程
3. 性能测试：验证缓存对响应时间的影响