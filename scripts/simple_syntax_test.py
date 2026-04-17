#!/usr/bin/env python3
"""
Simple Import Test - 直接测试语法
"""
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 直接导入模块文件
sys.path.insert(0, '/root/workspace/TradingAgents-CN')

def test_basic_imports():
    """测试基本导入（不依赖完整模块安装）"""
    
    test_results = []
    
    # Test 1: Calendar module
    try:
        logger.info("测试 TradingCalendar...")
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "tradingagents.calendar.trading_calendar",
            "/root/workspace/TradingAgents-CN/tradingagents/calendar/trading_calendar.py"
        )
        calendar_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(calendar_module)
        
        TradingCalendar = calendar_module.TradingCalendar
        Market = calendar_module.Market
        
        calendar = TradingCalendar()
        logger.info("✅ TradingCalendar 实例化成功")
        test_results.append(("TradingCalendar", True, None))
    except Exception as e:
        logger.error(f"❌ TradingCalendar 测试失败: {e}")
        test_results.append(("TradingCalendar", False, str(e)))
    
    # Test 2: TradingDayUtils
    try:
        logger.info("测试 TradingDayUtils...")
        # 直接加载文件
        with open('/root/workspace/TradingAgents-CN/tradingagents/utils/trading_day_utils.py', 'r') as f:
            code = f.read()
        
        # 检查语法
        compile(code, 'trading_day_utils.py', 'exec')
        logger.info("✅ TradingDayUtils 语法正确")
        test_results.append(("TradingDayUtils语法", True, None))
    except Exception as e:
        logger.error(f"❌ TradingDayUtils 语法测试失败: {e}")
        test_results.append(("TradingDayUtils语法", False, str(e)))
    
    # Test 3: EnhancedMongoDBCacheAdapter
    try:
        logger.info("测试 EnhancedMongoDBCacheAdapter...")
        with open('/root/workspace/TradingAgents-CN/tradingagents/dataflows/cache/enhanced_mongodb_adapter.py', 'r') as f:
            code = f.read()
        
        compile(code, 'enhanced_mongodb_adapter.py', 'exec')
        logger.info("✅ EnhancedMongoDBCacheAdapter 语法正确")
        test_results.append(("EnhancedMongoDBCacheAdapter语法", True, None))
    except Exception as e:
        logger.error(f"❌ EnhancedMongoDBCacheAdapter 语法测试失败: {e}")
        test_results.append(("EnhancedMongoDBCacheAdapter语法", False, str(e)))
    
    # Test 4: ResilientChinaStockProviderEnhanced
    try:
        logger.info("测试 ResilientChinaStockProviderEnhanced...")
        with open('/root/workspace/TradingAgents-CN/tradingagents/dataflows/providers/china/resilient_provider_enhanced.py', 'r') as f:
            code = f.read()
        
        compile(code, 'resilient_provider_enhanced.py', 'exec')
        logger.info("✅ ResilientChinaStockProviderEnhanced 语法正确")
        test_results.append(("ResilientChinaStockProviderEnhanced语法", True, None))
    except Exception as e:
        logger.error(f"❌ ResilientChinaStockProviderEnhanced 语法测试失败: {e}")
        test_results.append(("ResilientChinaStockProviderEnhanced语法", False, str(e)))
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("语法测试总结:")
    logger.info("="*60)
    
    for name, success, error in test_results:
        if success:
            logger.info(f"✅ {name}: 成功")
        else:
            logger.error(f"❌ {name}: 失败 - {error}")
    
    total_tests = len(test_results)
    success_count = sum(1 for _, success, _ in test_results if success)
    
    logger.info("="*60)
    logger.info(f"总测试数: {total_tests}")
    logger.info(f"成功数: {success_count}")
    logger.info(f"失败数: {total_tests - success_count}")
    logger.info("="*60)
    
    return success_count == total_tests


if __name__ == '__main__':
    success = test_basic_imports()
    sys.exit(0 if success else 1)