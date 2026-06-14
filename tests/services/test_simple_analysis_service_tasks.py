import asyncio
import sys
import types
from datetime import datetime
from enum import Enum


def _install_import_stubs(monkeypatch):
    logging_init = types.ModuleType("tradingagents.utils.logging_init")
    logging_init.init_logging = lambda: None
    monkeypatch.setitem(sys.modules, "tradingagents.utils.logging_init", logging_init)

    trading_graph = types.ModuleType("tradingagents.graph.trading_graph")
    trading_graph.TradingAgentsGraph = object
    monkeypatch.setitem(sys.modules, "tradingagents.graph.trading_graph", trading_graph)

    default_config = types.ModuleType("tradingagents.default_config")
    default_config.DEFAULT_CONFIG = {}
    monkeypatch.setitem(sys.modules, "tradingagents.default_config", default_config)

    models_pkg = types.ModuleType("app.models")
    models_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "app.models", models_pkg)

    analysis_models = types.ModuleType("app.models.analysis")

    class _AnalysisStatus(str, Enum):
        PENDING = "pending"
        PROCESSING = "processing"
        COMPLETED = "completed"
        FAILED = "failed"
        CANCELLED = "cancelled"

    class _DummyModel:
        pass

    analysis_models.AnalysisStatus = _AnalysisStatus
    analysis_models.AnalysisTask = _DummyModel
    analysis_models.SingleAnalysisRequest = _DummyModel
    analysis_models.AnalysisParameters = _DummyModel
    monkeypatch.setitem(sys.modules, "app.models.analysis", analysis_models)

    user_models = types.ModuleType("app.models.user")
    user_models.PyObjectId = str
    monkeypatch.setitem(sys.modules, "app.models.user", user_models)

    notification_models = types.ModuleType("app.models.notification")
    notification_models.NotificationCreate = _DummyModel
    monkeypatch.setitem(sys.modules, "app.models.notification", notification_models)

    database_mod = types.ModuleType("app.core.database")
    database_mod.get_mongo_db = lambda: None
    monkeypatch.setitem(sys.modules, "app.core.database", database_mod)

    config_service_mod = types.ModuleType("app.services.config_service")
    config_service_mod.ConfigService = lambda: object()
    monkeypatch.setitem(sys.modules, "app.services.config_service", config_service_mod)

    memory_mod = types.ModuleType("app.services.memory_state_manager")

    class _TaskStatus(Enum):
        PENDING = "pending"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        CANCELLED = "cancelled"

    memory_mod.TaskStatus = _TaskStatus
    memory_mod.get_memory_state_manager = lambda: None
    monkeypatch.setitem(sys.modules, "app.services.memory_state_manager", memory_mod)

    redis_mod = types.ModuleType("app.services.redis_progress_tracker")
    redis_mod.RedisProgressTracker = object
    redis_mod.get_progress_by_id = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "app.services.redis_progress_tracker", redis_mod)

    progress_mod = types.ModuleType("app.services.progress_log_handler")
    progress_mod.register_analysis_tracker = lambda *args, **kwargs: None
    progress_mod.unregister_analysis_tracker = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "app.services.progress_log_handler", progress_mod)

    bson_mod = types.ModuleType("bson")
    bson_mod.ObjectId = str
    monkeypatch.setitem(sys.modules, "bson", bson_mod)


def _lookup(doc, dotted_key):
    value = doc
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _matches(doc, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(doc, item) for item in expected):
                return False
        elif key == "$and":
            if not all(_matches(doc, item) for item in expected):
                return False
        elif isinstance(expected, dict) and "$in" in expected:
            if _lookup(doc, key) not in expected["$in"]:
                return False
        elif isinstance(expected, dict) and ("$gte" in expected or "$lte" in expected):
            value = _lookup(doc, key)
            if value is None:
                return False
            if "$gte" in expected and value < expected["$gte"]:
                return False
            if "$lte" in expected and value > expected["$lte"]:
                return False
        elif isinstance(expected, dict) and "$in" not in expected:
            if not _matches(_lookup(doc, key) or {}, expected):
                return False
        elif _lookup(doc, key) != expected:
            return False
    return True


class _AsyncCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *args, **kwargs):
        return self

    def limit(self, limit):
        self._docs = self._docs[:limit]
        return self

    def __aiter__(self):
        self._iter = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _FakeAnalysisTasks:
    def __init__(self, docs):
        self.docs = list(docs)

    async def count_documents(self, query):
        return len([doc for doc in self.docs if _matches(doc, query)])

    def find(self, query, projection=None):
        if projection == {"task_id": 1}:
            return _AsyncCursor([{"task_id": doc.get("task_id")} for doc in self.docs if _matches(doc, query)])
        return _AsyncCursor([doc for doc in self.docs if _matches(doc, query)])


class _FakeDB:
    def __init__(self, docs):
        self.analysis_tasks = _FakeAnalysisTasks(docs)


class _FakeMemoryManager:
    def __init__(self, tasks):
        self.tasks = list(tasks)
        self.requested_limits = []

    async def list_user_tasks(self, user_id, status=None, limit=20, offset=0):
        self.requested_limits.append(limit)
        return self.tasks[offset:offset + limit]


def _make_service(monkeypatch, memory_tasks, mongo_docs=None):
    _install_import_stubs(monkeypatch)
    from app.services.simple_analysis_service import SimpleAnalysisService
    import app.services.simple_analysis_service as service_mod

    svc = SimpleAnalysisService.__new__(SimpleAnalysisService)
    svc.memory_manager = _FakeMemoryManager(memory_tasks)
    svc._stock_name_cache = {}
    monkeypatch.setattr(service_mod, "get_mongo_db", lambda: _FakeDB(mongo_docs or []), raising=True)
    return svc


def test_running_memory_task_counts_when_matching_mongo_doc_has_processing_status(monkeypatch):
    async def _run():
        memory_task = {
            "task_id": "task-1",
            "user_id": "user-1",
            "stock_code": "000001",
            "status": "running",
            "start_time": "2026-06-15T10:00:00",
        }
        mongo_doc = {
            "task_id": "task-1",
            "user_id": "user-1",
            "stock_code": "000001",
            "status": "processing",
            "created_at": datetime(2026, 6, 15, 10, 0, 0),
        }
        svc = _make_service(monkeypatch, [memory_task], [mongo_doc])

        tasks, total = await svc.list_user_tasks("user-1", status="processing", limit=20, offset=0)

        assert len(tasks) == 1
        assert total == 1

    asyncio.run(_run())


def test_memory_tasks_after_first_window_are_counted_and_pageable(monkeypatch):
    async def _run():
        memory_tasks = [
            {
                "task_id": f"task-{idx}",
                "user_id": "user-1",
                "stock_code": f"00000{idx}",
                "status": "running",
                "start_time": f"2026-06-15T10:0{idx}:00",
            }
            for idx in range(5)
        ]
        svc = _make_service(monkeypatch, memory_tasks, [])

        tasks, total = await svc.list_user_tasks("user-1", status="processing", limit=1, offset=3)

        assert [task["task_id"] for task in tasks] == ["task-1"]
        assert total == 5

    asyncio.run(_run())


def test_date_range_requires_same_timestamp_field_to_match(monkeypatch):
    async def _run():
        out_of_range_doc = {
            "task_id": "task-out",
            "user_id": "user-1",
            "stock_code": "000001",
            "status": "completed",
            "created_at": datetime(2026, 6, 1, 10, 0, 0),
            "started_at": datetime(2026, 6, 20, 10, 0, 0),
        }
        svc = _make_service(monkeypatch, [], [out_of_range_doc])

        tasks, total = await svc.list_user_tasks(
            "user-1",
            status="completed",
            limit=20,
            offset=0,
            start_date="2026-06-10",
            end_date="2026-06-12",
        )

        assert tasks == []
        assert total == 0

    asyncio.run(_run())
