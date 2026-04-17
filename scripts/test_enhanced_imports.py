#!/usr/bin/env python3
"""
Import Test - 测试新创建的模块是否可以正确导入
"""
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_imports():
    """测试所有模块的导入"""
    
    test_results = []
    
    # Test 1: TradingCalendar
    try:
        logger.info("测试导入 TradingCalendar...")
        from tradingagents.calendar.trading_calendar import TradingCalendar, Market
        logger.info("✅ TradingCalendar 导入成功")
        test_results.append(("TradingCalendar", True, None))
    except Exception as e:
        logger.error(f"❌ TradingCalendar 导入失败: {e}")
        test_results.append(("TradingCalendar", False, str(e)))
    
    # Test 2: TradingDayUtils
    try:
        logger.info("测试导入 TradingDayUtils...")
        from tradingagents.utils.trading_day_utils import TradingDayUtils
        logger.info("✅ TradingDayUtils 导入成功")
        test_results.append(("TradingDayUtils", True, None))
    except Exception as e:
        logger.error(f"❌ TradingDayUtils 导入失败: {e}")
        test_results.append(("TradingDayUtils", False, str(e)))
    
    # Test 3: EnhancedMongoDBCacheAdapter
    try:
        logger.info("测试导入 EnhancedMongoDBCacheAdapter...")
        from tradingagents.dataflows.cache.enhanced_mongodb_adapter import EnhancedMongoDBCacheAdapter
        logger.info("✅ EnhancedMongoDBCacheAdapter 导入成功")
        test_results.append(("EnhancedMongoDBCacheAdapter", True, None))
    except Exception as e:
        logger.error(f"❌ EnhancedMongoDBCacheAdapter 导入失败: {e}")
        test_results.append(("EnhancedMongoDBCacheAdapter", False, str(e)))
    
    # Test 4: ResilientChinaStockProviderEnhanced
    try:
        logger.info("测试导入 ResilientChinaStockProviderEnhanced...")
        from tradingagents.dataflows.providers.china.resilient_provider_enhanced import ResilientChinaStockProviderEnhanced
        logger.info("✅ ResilientChinaStockProviderEnhanced 导入成功")
        test_results.append(("ResilientChinaStockProviderEnhanced", True, None))
    except Exception as e:
        logger.error(f"❌ ResilientChinaStockProviderEnhanced 导入失败: {e}")
        test_results.append(("ResilientChinaStockProviderEnhanced", False, str(e)))
    
    # Test 5: DataFetchError
    try:
        logger.info("测试导入 DataFetchError...")
        from tradingagents.dataflows.providers.china.resilient_provider_enhanced import DataFetchError
        logger.info("✅ DataFetchError 导入成功")
        test_results.append(("DataFetchError", True, None))
    except Exception as e:
        logger.error(f"❌ DataFetchError 导入失败: {e}")
        test_results.append(("DataFetchError", False, str(e)))
    
    # Test 6: TradingCalendar functionality
    try:
        logger.info("测试 TradingCalendar 功能...")
        calendar = TradingCalendar()
        is_trading = calendar.is_trading_day(Market.CN, '2026-04-16')
        logger.info(f"   2026-04-16 是交易日? {is_trading}")
        prev_day = calendar.get_previous_trading_day(Market.CN, '2026-04-16')
        logger.info(f"   上一个交易日: {prev_day}")
        logger.info("✅ TradingCalendar 功能正常")
        test_results.append(("TradingCalendar功能", True, None))
    except Exception as e:
        logger.error(f"❌ TradingCalendar 功能测试失败: {e}")
        test_results.append(("TradingCalendar功能", False, str(e)))
    
    # Test 7: TradingDayUtils functionality
    try:
        logger.info("测试 TradingDayUtils 功能...")
        one_year_ago = TradingDayUtils.get_one_year_ago_trading_day()
        logger.info(f"   一年前交易日: {one_year_ago}")
        latest_closed = TradingDayUtils.get_latest_closed_trading_day()
        logger.info(f"   最近已收盘交易日: {latest_closed}")
        logger.info("✅ TradingDayUtils 功能正常")
        test_results.append(("TradingDayUtils功能", True, None))
    except Exception as e:
        logger.error(f"❌ TradingDayUtils 功能测试失败: {e}")
        test_results.append(("TradingDayUtils功能", False, str(e)))
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("导入测试总结:")
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
    success = test_imports()
    sys.exit(0 if success else 1)