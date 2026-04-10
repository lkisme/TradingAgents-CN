#!/usr/bin/env python3
"""
测试 Resilient Provider 功能
验证 AKShare 失败时自动切换到 BaoStock
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tradingagents.dataflows.providers.china.resilient_provider import ResilientChinaStockProvider, get_resilient_provider


async def test_resilient_provider():
    """测试 Resilient Provider 的基本功能"""
    
    print("=" * 60)
    print("🧪 Resilient Provider 功能测试")
    print("=" * 60)
    
    # 1. 初始化 Provider
    print("\n1️⃣ 初始化 Resilient Provider...")
    provider = ResilientChinaStockProvider()
    
    # 检查初始化状态
    print(f"   - 连接状态: {provider.connected}")
    print(f"   - 数据源优先级: {provider._source_priority}")
    print(f"   - AKShare Provider: {provider._providers.get('akshare')}")
    print(f"   - BaoStock Provider: {provider._providers.get('baostock')}")
    
    # 2. 测试获取历史数据
    print("\n2️️️️ 测试获取历史数据...")
    test_cases = [
        ("600519", "2025-01-01", "2025-03-31"),  # 贵州茅台（上海）
        ("000001", "2025-01-01", "2025-03-31"),  # 平安银行（深圳）
        ("300750", "2025-01-01", "2025-03-31"),  # 宁德时代（创业板）
    ]
    
    for code, start_date, end_date in test_cases:
        print(f"\n   📊 测试股票: {code} ({start_date} 到 {end_date})")
        
        try:
            df = await provider.get_historical_data(code, start_date, end_date)
            
            if df is not None and not df.empty:
                print(f"   ✅ 数据获取成功!")
                print(f"   - 数据条数: {len(df)}")
                print(f"   - 数据源: {provider.get_current_source()}")
                print(f"   - 列名: {list(df.columns)[:10]}...")
                print(f"\n   前5行数据:")
                print(df.head().to_string())
            else:
                print(f"   ❌ 数据获取失败，返回空数据")
                
        except Exception as e:
            print(f"   ❌ 测试异常: {e}")
    
    # 3. 测试获取股票基本信息
    print("\n\n3️️️️ 测试获取股票基本信息...")
    for code in ["600519", "000001"]:
        print(f"\n   📊 测试股票: {code}")
        try:
            info = await provider.get_stock_basic_info(code)
            if info:
                print(f"   ✅ 信息获取成功!")
                print(f"   - 名称: {info.get('name')}")
                print(f"   - 行业: {info.get('industry')}")
                print(f"   - 数据源: {provider.get_current_source()}")
            else:
                print(f"   ❌ 信息获取失败")
        except Exception as e:
            print(f"   ❌ 测试异常: {e}")
    
    # 4. 测试数据格式标准化
    print("\n\n4️️️️ 测试数据格式标准化...")
    df = await provider.get_historical_data("600519", "2025-01-01", "2025-03-31")
    
    if df is not None and not df.empty:
        print(f"   ✅ 数据格式检查:")
        
        # 检查必需列是否存在
        required_columns = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'code']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            print(f"   ❌ 缺少列: {missing_columns}")
        else:
            print(f"   ✅ 所有必需列都存在: {required_columns}")
        
        # 检查数据类型
        print(f"\n   数据类型检查:")
        for col in ['open', 'close', 'high', 'low', 'volume', 'amount']:
            if col in df.columns:
                print(f"   - {col}: {df[col].dtype}")
    
    print("\n" + "=" * 60)
    print("🎉 测试完成!")
    print("=" * 60)


async def test_fallback_mechanism():
    """测试降级机制（模拟 AKShare 失败）"""
    
    print("\n" + "=" * 60)
    print("🧪 降级机制测试（模拟 AKShare 失败）")
    print("=" * 60)
    
    # 创建 Provider，但设置 AKShare 优先级较低
    provider = ResilientChinaStockProvider(source_priority=["baostock", "akshare"])
    
    print(f"\n调整数据源优先级: {provider._source_priority}")
    print(f"（优先使用 BaoStock，然后是 AKShare）")
    
    # 测试获取数据
    print("\n📊 测试获取历史数据...")
    df = await provider.get_historical_data("600519", "2025-01-01", "2025-03-31")
    
    if df is not None and not df.empty:
        print(f"✅ 数据获取成功!")
        print(f"   - 数据条数: {len(df)}")
        print(f"   - 实际数据源: {provider.get_current_source()}")
        
        if provider.get_current_source() == "baostock":
            print(f"   ✅ 降级机制生效，成功切换到 BaoStock")
        else:
            print(f"   ⚠️ 使用了其他数据源: {provider.get_current_source()}")
    else:
        print(f"❌ 数据获取失败")
    
    print("\n" + "=" * 60)
    print("🎉 降级机制测试完成!")
    print("=" * 60)


async def test_data_source_manager():
    """测试 Data Source Manager 的 Resilient Provider 集成"""
    
    print("\n" + "=" * 60)
    print("🧪 Data Source Manager 集成测试")
    print("=" * 60)
    
    from tradingagents.dataflows.data_source_manager import get_data_source_manager
    
    manager = get_data_source_manager()
    
    print(f"\n当前数据源: {manager.current_source.value}")
    print(f"可用数据源: {[s.value for s in manager.available_sources]}")
    
    # 测试 Resilient 模式
    print("\n📊 测试 Resilient 模式获取数据...")
    result = manager.get_stock_data_resilient("600519", "2025-01-01", "2025-03-31")
    
    print(f"\n结果:")
    print(result[:500] + "..." if len(result) > 500 else result)
    
    print("\n" + "=" * 60)
    print("🎉 Data Source Manager 集成测试完成!")
    print("=" * 60)


async def main():
    """主测试函数"""
    
    print("\n" + "=" * 60)
    print("🧪 开始运行 Resilient Provider 完整测试")
    print("=" * 60)
    
    try:
        # 1. 基本功能测试
        await test_resilient_provider()
        
        # 2. 降级机制测试
        await test_fallback_mechanism()
        
        # 3. Data Source Manager 集成测试
        await test_data_source_manager()
        
        print("\n✅ 所有测试通过!")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())