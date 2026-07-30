import asyncio
import sys
import types
from typing import Any, Dict, List


def _install_database_stub(monkeypatch):
    database_mod = types.ModuleType("app.core.database")
    database_mod.get_mongo_db = lambda: None
    monkeypatch.setitem(sys.modules, "app.core.database", database_mod)


def test_enhanced_screening_enriches_from_db(monkeypatch):
    _install_database_stub(monkeypatch)

    # Late import to patch module symbols correctly
    from app.services.enhanced_screening_service import EnhancedScreeningService

    # Fake DB layer
    class FakeCursor:
        def __init__(self, docs: List[Dict[str, Any]]):
            self._docs = docs

        async def to_list(self, length: int):
            return self._docs

    class FakeColl:
        def __init__(self, docs):
            self._docs = docs

        def find(self, query, projection=None):
            return FakeCursor(self._docs)

    class FakeDB:
        def __init__(self, docs):
            self._coll = FakeColl(docs)

        def __getitem__(self, name: str):
            return self._coll

    # Prepare quotes in DB for codes 000001, 600000
    quotes_docs = [
        {"code": "000001", "close": 10.5, "pct_chg": 1.2, "amount": 1.23e8},
        {"code": "600000", "close": 9.9, "pct_chg": -0.5, "amount": 8.76e7},
    ]

    # Patch get_mongo_db used inside enhanced_screening_service module
    import app.services.enhanced_screening_service as ess_mod

    def _fake_get_mongo_db():
        return FakeDB(quotes_docs)

    monkeypatch.setattr(ess_mod, "get_mongo_db", _fake_get_mongo_db, raising=True)

    # Patch condition analysis to force DB path
    def _fake_analyze(_self, _conditions):
        return {"can_use_database": True, "needs_technical_indicators": False}

    monkeypatch.setattr(EnhancedScreeningService, "_analyze_conditions", _fake_analyze, raising=True)

    # Patch db_service.screen_stocks to return minimal items with codes
    class _FakeDbService:
        async def screen_stocks(self, conditions, limit, offset, order_by):
            items = [
                {"code": "1", "name": "平安银行"},
                {"code": "600000", "name": "浦发银行"},
                {"code": "300750", "name": "宁德时代"},  # not present in quotes -> stays None
            ]
            total = len(items)
            return items, total

    async def _run():
        svc = EnhancedScreeningService()
        svc.db_service = _FakeDbService()
        res = await svc.screen_stocks(conditions=[])
        items = res["items"]
        # Map by code for assertion
        by_code = {str(it["code"]).zfill(6): it for it in items}
        assert by_code["000001"]["close"] == 10.5
        assert by_code["000001"]["pct_chg"] == 1.2
        assert by_code["600000"]["amount"] == 8.76e7
        # Code not present in DB remains without enrichment
        assert "close" not in by_code["300750"] or by_code["300750"]["close"] is None

    asyncio.run(_run())


def test_quotes_ingestion_run_once_writes_bulk(monkeypatch):
    _install_database_stub(monkeypatch)

    from app.services.quotes_ingestion_service import QuotesIngestionService
    import app.services.quotes_ingestion_service as qis_mod

    # Fake DataSourceManager to avoid external calls when resolving trade date
    class _FakeManager:
        def find_latest_trade_date_with_fallback(self):
            return "20260728"

    monkeypatch.setattr(qis_mod, "DataSourceManager", _FakeManager, raising=True)

    async def _fake_fetch(self, source_type, akshare_api=None):
        return (
            {
                "000001": {"close": 10.1, "pct_chg": 0.1, "amount": 1.0e8},
                "600000": {"close": 9.8, "pct_chg": -0.3, "amount": 7.5e7},
            },
            "fake",
        )

    monkeypatch.setattr(QuotesIngestionService, "_fetch_quotes_from_source_async", _fake_fetch, raising=True)
    monkeypatch.setattr(qis_mod.settings, "QUOTES_AUTO_DETECT_TUSHARE_PERMISSION", False, raising=False)

    # Capture bulk_write ops
    class _FakeResult:
        def __init__(self, upserted):
            self.matched_count = 0
            self.modified_count = 0
            self.upserted_ids = {i: None for i in range(upserted)}

    class _FakeColl:
        def __init__(self):
            self.last_ops = None

        async def create_index(self, *args, **kwargs):
            return "ok"

        async def bulk_write(self, ops, ordered=False):
            self.last_ops = ops
            return _FakeResult(len(ops))

    class _FakeDB:
        def __init__(self):
            self._coll = _FakeColl()

        def __getitem__(self, name: str):
            return self._coll

    fake_db = _FakeDB()

    def _fake_get_mongo_db():
        return fake_db

    monkeypatch.setattr(qis_mod, "get_mongo_db", _fake_get_mongo_db, raising=True)

    async def _run():
        svc = QuotesIngestionService()
        # Force trading time to True
        monkeypatch.setattr(QuotesIngestionService, "_is_trading_time", lambda self, now=None: True, raising=True)
        await svc.run_once()
        # Verify that two upsert operations were generated
        assert fake_db._coll.last_ops is not None
        assert len(fake_db._coll.last_ops) == 2

    import asyncio
    asyncio.run(_run())


def test_quotes_ingestion_times_out_blocking_quote_fetch(monkeypatch):
    _install_database_stub(monkeypatch)

    from app.services.quotes_ingestion_service import QuotesIngestionService
    import app.services.quotes_ingestion_service as qis_mod

    async def _noop_record_status(self, **kwargs):
        self.recorded_status = kwargs

    async def _slow_fetch(self, source_type, akshare_api=None):
        await asyncio.sleep(0.2)
        return {"000001": {"close": 10.1}}, "slow"

    class _FakeManager:
        def find_latest_trade_date_with_fallback(self):
            return "20260728"

    monkeypatch.setattr(QuotesIngestionService, "_is_trading_time", lambda self, now=None: True, raising=True)
    monkeypatch.setattr(QuotesIngestionService, "_fetch_quotes_from_source_async", _slow_fetch, raising=True)
    monkeypatch.setattr(QuotesIngestionService, "_record_sync_status", _noop_record_status, raising=True)
    monkeypatch.setattr(qis_mod, "DataSourceManager", _FakeManager, raising=True)
    monkeypatch.setattr(qis_mod.settings, "QUOTES_AUTO_DETECT_TUSHARE_PERMISSION", False, raising=False)
    monkeypatch.setattr(qis_mod.settings, "QUOTES_INGEST_FETCH_TIMEOUT_SECONDS", 0.01, raising=False)

    async def _run():
        svc = QuotesIngestionService()
        started = asyncio.get_running_loop().time()
        await svc.run_once()
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 0.1
        assert svc.recorded_status["success"] is False
        assert "超时" in svc.recorded_status["error_msg"]

    import asyncio
    asyncio.run(_run())


def test_quotes_ingestion_times_out_tushare_permission_check(monkeypatch):
    _install_database_stub(monkeypatch)

    from app.services.quotes_ingestion_service import QuotesIngestionService
    import app.services.quotes_ingestion_service as qis_mod

    async def _fake_fetch(self, source_type, akshare_api=None):
        return {"000001": {"close": 10.1}}, "fake"

    async def _noop_bulk_upsert(self, quotes_map, trade_date, source):
        self.upserted = {
            "quotes_map": quotes_map,
            "trade_date": trade_date,
            "source": source,
        }

    async def _noop_record_status(self, **kwargs):
        self.recorded_status = kwargs

    async def _slow_permission_check(self):
        await asyncio.sleep(0.2)
        return True

    class _FakeManager:
        def find_latest_trade_date_with_fallback(self):
            return "20260728"

    monkeypatch.setattr(QuotesIngestionService, "_is_trading_time", lambda self, now=None: True, raising=True)
    monkeypatch.setattr(QuotesIngestionService, "_check_tushare_permission_async", _slow_permission_check, raising=True)
    monkeypatch.setattr(QuotesIngestionService, "_fetch_quotes_from_source_async", _fake_fetch, raising=True)
    monkeypatch.setattr(QuotesIngestionService, "_bulk_upsert", _noop_bulk_upsert, raising=True)
    monkeypatch.setattr(QuotesIngestionService, "_record_sync_status", _noop_record_status, raising=True)
    monkeypatch.setattr(qis_mod, "DataSourceManager", _FakeManager, raising=True)
    monkeypatch.setattr(qis_mod.settings, "QUOTES_AUTO_DETECT_TUSHARE_PERMISSION", True, raising=False)
    monkeypatch.setattr(qis_mod.settings, "QUOTES_INGEST_FETCH_TIMEOUT_SECONDS", 0.01, raising=False)

    async def _run():
        svc = QuotesIngestionService()
        started = asyncio.get_running_loop().time()
        await svc.run_once()
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 0.1
        assert svc._tushare_permission_checked is True
        assert svc._tushare_has_premium is False
        assert svc.upserted["quotes_map"] == {"000001": {"close": 10.1}}

    import asyncio
    asyncio.run(_run())
