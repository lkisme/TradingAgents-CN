#!/usr/bin/env python3
"""
单元测试: SinaKlineSyncService

测试新浪 K 线数据同步服务
- 数据转换逻辑
- 随机间隔生成
- 不完整股票查询（基于数据库聚合统计）
- 单只股票同步
"""
import pytest
import asyncio
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
        service.db = Mock()  # Mock 数据库
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
        
        # 验证第二条有 pre_close（精度用 abs 比较）
        assert result[1]["pre_close"] == 8.07
        assert result[1]["change"] == 0.23
        assert abs(result[1]["pct_chg"] - 2.85) < 0.01  # 0.23/8.07*100 ≈ 2.85
        
        # 验证第三条的 pre_close 和涨跌幅
        assert result[2]["pre_close"] == 8.30
        assert result[2]["change"] == 0.20
        assert abs(result[2]["pct_chg"] - 2.41) < 0.01  # 0.20/8.30*100 ≈ 2.41

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

    def test_transform_data_invalid_values(self, service):
        """测试无效值处理"""
        raw_data = [
            {"day": "2026-04-20", "open": "invalid", "high": "8.25", "low": "7.98", "close": "8.07", "volume": "13012206"},
        ]
        
        # 应该抛出异常或跳过
        # 当前实现会抛出 ValueError，导致该条数据被跳过
        result = service._transform_data(raw_data, "601339")
        # 无效数据会被跳过，返回空列表
        assert result == []

    def test_transform_data_missing_fields(self, service):
        """测试缺失字段处理"""
        raw_data = [
            {"day": "2026-04-20"},  # 缺少 OHLCV 字段
        ]
        
        result = service._transform_data(raw_data, "601339")
        
        # 应该能处理缺失字段，使用默认值 0
        assert len(result) == 1
        assert result[0]["open"] == 0
        assert result[0]["high"] == 0
        assert result[0]["close"] == 0

    @pytest.mark.asyncio
    async def test_get_incomplete_stocks_empty_pool(self, service):
        """测试股票池为空的情况"""
        # Mock get_stock_pool_for_sync 返回空列表
        with patch('app.services.stock_pool_service.get_stock_pool_for_sync') as mock_pool:
            mock_pool.return_value = []
            
            result = await service.get_incomplete_stocks()
            
            assert result == []

    @pytest.mark.asyncio
    async def test_get_incomplete_stocks_no_data(self, service):
        """测试股票无历史数据的情况"""
        # Mock 股票池
        with patch('app.services.stock_pool_service.get_stock_pool_for_sync') as mock_pool:
            mock_pool.return_value = ["601339", "600908"]
            
            # Mock 聚合查询返回空（无历史数据）
            mock_cursor = AsyncMock()
            mock_cursor.to_list = AsyncMock(return_value=[])
            service.db.stock_daily_quotes.aggregate = Mock(return_value=mock_cursor)
            
            # Mock TradingDayUtils
            with patch('tradingagents.utils.trading_day_utils.TradingDayUtils') as mock_utils:
                mock_utils.get_one_year_ago_trading_day.return_value = "2025-05-01"
                mock_utils.get_latest_closed_trading_day.return_value = "2026-05-01"
                
                result = await service.get_incomplete_stocks()
                
                # 无历史数据的股票应该返回
                assert "601339" in result
                assert "600908" in result

    @pytest.mark.asyncio
    async def test_get_incomplete_stocks_complete(self, service):
        """测试数据完整的股票"""
        with patch('app.services.stock_pool_service.get_stock_pool_for_sync') as mock_pool:
            mock_pool.return_value = ["601339"]
            
            # Mock 聚合查询返回完整数据范围
            mock_cursor = AsyncMock()
            mock_cursor.to_list = AsyncMock(return_value=[{
                "_id": None,
                "earliest_date": "2025-04-01",  # 一年前
                "latest_date": "2026-05-01",     # 最新收盘日
                "total_records": 250
            }])
            service.db.stock_daily_quotes.aggregate = Mock(return_value=mock_cursor)
            
            with patch('tradingagents.utils.trading_day_utils.TradingDayUtils') as mock_utils:
                mock_utils.get_one_year_ago_trading_day.return_value = "2025-05-01"
                mock_utils.get_latest_closed_trading_day.return_value = "2026-05-01"
                
                result = await service.get_incomplete_stocks()
                
                # 数据完整的股票不应该返回
                assert result == []

    @pytest.mark.asyncio
    async def test_get_incomplete_stocks_partial_data(self, service):
        """测试数据不完整的股票"""
        with patch('app.services.stock_pool_service.get_stock_pool_for_sync') as mock_pool:
            mock_pool.return_value = ["601339"]
            
            # Mock 聚合查询返回不完整数据范围
            mock_cursor = AsyncMock()
            mock_cursor.to_list = AsyncMock(return_value=[{
                "_id": None,
                "earliest_date": "2026-01-01",  # 不是一年前
                "latest_date": "2026-05-01",
                "total_records": 100
            }])
            service.db.stock_daily_quotes.aggregate = Mock(return_value=mock_cursor)
            
            with patch('tradingagents.utils.trading_day_utils.TradingDayUtils') as mock_utils:
                mock_utils.get_one_year_ago_trading_day.return_value = "2025-05-01"
                mock_utils.get_latest_closed_trading_day.return_value = "2026-05-01"
                
                result = await service.get_incomplete_stocks()
                
                # 数据不完整的股票应该返回
                assert "601339" in result

    @pytest.mark.asyncio
    async def test_sync_single_stock_success(self, service):
        """测试单只股票同步成功"""
        # Mock 新浪数据获取
        mock_sina_data = [
            {"trade_date": "2026-04-20", "open": 8.07, "high": 8.25, "low": 7.98, "close": 8.07, "volume": 13012206},
        ]
        
        with patch.object(service, 'fetch_kline_from_sina', return_value=mock_sina_data):
            # Mock 已有数据查询
            mock_cursor = AsyncMock()
            mock_cursor.to_list = AsyncMock(return_value=[])  # 无已有数据
            service.db.stock_daily_quotes.find = Mock(return_value=mock_cursor)
            
            # Mock 插入
            service.db.stock_daily_quotes.insert_many = Mock()
            
            result = await service.sync_single_stock("601339", datalen=100)
            
            assert result["symbol"] == "601339"
            assert result["status"] == "success"
            assert result["new_records"] == 1

    @pytest.mark.asyncio
    async def test_sync_single_stock_skipped(self, service):
        """测试单只股票同步跳过（数据已存在）"""
        mock_sina_data = [
            {"trade_date": "2026-04-20", "open": 8.07, "high": 8.25, "low": 7.98, "close": 8.07, "volume": 13012206},
        ]
        
        with patch.object(service, 'fetch_kline_from_sina', return_value=mock_sina_data):
            # Mock 已有数据查询返回相同日期
            mock_cursor = AsyncMock()
            mock_cursor.to_list = AsyncMock(return_value=[{"trade_date": "2026-04-20"}])
            service.db.stock_daily_quotes.find = Mock(return_value=mock_cursor)
            
            result = await service.sync_single_stock("601339", datalen=100)
            
            assert result["symbol"] == "601339"
            assert result["status"] == "skipped"
            assert result["new_records"] == 0

    @pytest.mark.asyncio
    async def test_sync_single_stock_failed(self, service):
        """测试单只股票同步失败"""
        with patch.object(service, 'fetch_kline_from_sina', return_value=[]):
            result = await service.sync_single_stock("601339", datalen=100)
            
            assert result["symbol"] == "601339"
            assert result["status"] == "failed"
            assert "error" in result


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


class TestFetchKlineFromSina:
    """新浪 API 获取测试"""

    @pytest.fixture
    def service(self):
        """创建服务实例"""
        service = SinaKlineSyncService()
        return service

    @pytest.mark.asyncio
    async def test_fetch_kline_success(self, service):
        """测试成功获取 K 线数据"""
        # Mock 响应
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '''[
            {"day": "2026-04-20", "open": "8.07", "high": "8.25", "low": "7.98", "close": "8.07", "volume": "13012206"},
            {"day": "2026-04-21", "open": "8.07", "high": "8.33", "low": "7.98", "close": "8.30", "volume": "12750300"}
        ]'''
        
        with patch('requests.get', return_value=mock_response):
            result = await service.fetch_kline_from_sina("601339", datalen=10)
            
            assert len(result) == 2
            assert result[0]["symbol"] == "601339"
            assert result[0]["trade_date"] == "2026-04-20"

    @pytest.mark.asyncio
    async def test_fetch_kline_non_200(self, service):
        """测试非 200 响应"""
        mock_response = Mock()
        mock_response.status_code = 500
        
        with patch('requests.get', return_value=mock_response):
            result = await service.fetch_kline_from_sina("601339", datalen=10)
            
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_kline_invalid_json(self, service):
        """测试无效 JSON 响应"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "invalid json"
        
        with patch('requests.get', return_value=mock_response):
            result = await service.fetch_kline_from_sina("601339", datalen=10)
            
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_kline_timeout(self, service):
        """测试请求超时"""
        import requests.exceptions
        
        with patch('requests.get', side_effect=requests.exceptions.Timeout()):
            result = await service.fetch_kline_from_sina("601339", datalen=10)
            
            assert result == []

    def test_datalen_limit(self, service):
        """测试 datalen 限制为 1023"""
        assert service.MAX_DATALEN == 1023


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])