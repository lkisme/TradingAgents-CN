#!/usr/bin/env python3
"""
单元测试: SinaKlineSyncService
"""
import pytest
import asyncio
import random
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

# 测试导入
from app.services.sina_kline_sync_service import (
    SinaKlineSyncService,
    get_sina_kline_sync_service,
)


class TestSinaKlineSyncService:
    """SinaKlineSyncService 单元测试"""

    @pytest.fixture
    def service(self):
        """创建服务实例"""
        service = SinaKlineSyncService()
        service._db = Mock()  # Mock 数据库
        return service

    def test_get_random_interval(self, service):
        """测试随机间隔返回 0.3-0.6"""
        for _ in range(100):
            interval = service._get_random_interval()
            assert 0.3 <= interval <= 0.6, f"间隔 {interval} 不在 0.3-0.6 范围内"

    def test_transform_data_basic(self, service):
        """测试字段转换基本功能"""
        # 模拟新浪 API 返回数据
        raw_data = [
            {"day": "2026-04-20", "open": "8.07", "high": "8.25", "low": "7.98", "close": "8.07", "volume": "13012206"},
            {"day": "2026-04-21", "open": "8.07", "high": "8.33", "low": "7.98", "close": "8.30", "volume": "12750300"},
            {"day": "2026-04-22", "open": "8.23", "high": "8.59", "low": "8.10", "close": "8.50", "volume": "15546446"},
        ]
        
        result = service._transform_data(raw_data, "601339")
        
        # 验证基本字段
        assert len(result) == 3
        assert result[0]["symbol"] == "601339"
        assert result[0]["code"] == "601339"
        assert result[0]["full_symbol"] == "601339.SH"
        assert result[0]["market"] == "CN"
        assert result[0]["data_source"] == "sina_kline"
        
        # 验证数值字段
        assert result[0]["open"] == 8.07
        assert result[0]["high"] == 8.25
        assert result[0]["low"] == 7.98
        assert result[0]["close"] == 8.07
        assert result[0]["volume"] == 13012206
        
        # 验证 amount = 0（设计要求）
        assert result[0]["amount"] == 0
        
        # 验证第一条无 pre_close
        assert result[0]["pre_close"] is None
        assert result[0]["change"] is None
        assert result[0]["pct_chg"] is None
        
        # 验证第二条有 pre_close
        assert result[1]["pre_close"] == 8.07
        assert result[1]["change"] == 0.23
        assert result[1]["pct_chg"] == 2.84

    def test_transform_data_sz_stock(self, service):
        """测试深市股票转换"""
        raw_data = [
            {"day": "2026-04-24", "open": "6.80", "high": "7.21", "low": "6.80", "close": "7.21", "volume": "9203800"},
        ]
        
        result = service._transform_data(raw_data, "002095")
        
        assert result[0]["full_symbol"] == "002095.SZ"
        assert result[0]["market"] == "CN"

    def test_transform_data_empty(self, service):
        """测试空数据处理"""
        result = service._transform_data([], "601339")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_incomplete_stocks(self, service):
        """测试获取不完整股票列表"""
        # Mock 数据库查询
        mock_cursor = AsyncMock()
        mock_cursor.__aiter__.return_value = [
            {"symbol": "601339"},
            {"symbol": "600908"},
        ]
        service._db.cache_metadata.find = Mock(return_value=mock_cursor)
        
        result = await service.get_incomplete_stocks()
        
        # 验证查询条件
        service._db.cache_metadata.find.assert_called_once()
        call_args = service._db.cache_metadata.find.call_args[0][0]
        assert call_args["collection"] == "stock_daily_quotes"
        assert call_args["is_complete"] == False

    def test_update_metadata(self, service):
        """测试元数据更新"""
        # Mock 数据库操作
        service._db.cache_metadata.update_one = Mock()
        service._db.stock_daily_quotes.count_documents = Mock(return_value=250)
        
        # 模拟同步后的数据
        data = [
            {"trade_date": "2025-04-11"},
            {"trade_date": "2026-04-24"},
        ]
        
        # Mock TradingDayUtils
        with patch('tradingagents.utils.trading_day_utils.TradingDayUtils') as mock_utils:
            mock_utils.get_one_year_ago_trading_day.return_value = "2025-04-25"
            mock_utils.get_latest_closed_trading_day.return_value = "2026-04-24"
            
            service._update_metadata("601339", data)
        
        # 验证 update_one 被调用
        service._db.cache_metadata.update_one.assert_called_once()
        call_args = service._db.cache_metadata.update_one.call_args
        
        # 验证查询条件
        assert call_args[0][0]["symbol"] == "601339"
        assert call_args[0][0]["collection"] == "stock_daily_quotes"
        
        # 验证更新字段
        update_data = call_args[0][1]["$set"]
        assert update_data["earliest_date"] == "2025-04-11"
        assert update_data["latest_date"] == "2026-04-24"
        assert update_data["total_records"] == 250
        assert update_data["data_source"] == "sina_kline"


class TestRandomIntervalDistribution:
    """随机间隔分布测试"""

    def test_interval_distribution(self):
        """测试随机间隔的分布均匀性"""
        service = SinaKlineSyncService()
        intervals = [service._get_random_interval() for _ in range(1000)]
        
        # 计算统计量
        mean = sum(intervals) / len(intervals)
        min_val = min(intervals)
        max_val = max(intervals)
        
        # 验证范围
        assert min_val >= 0.3
        assert max_val <= 0.6
        
        # 验证均值接近中间值
        assert 0.4 <= mean <= 0.5, f"均值 {mean} 不在期望范围 0.4-0.5"


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])