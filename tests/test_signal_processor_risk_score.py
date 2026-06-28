#!/usr/bin/env python3
"""Regression tests for risk score extraction in SignalProcessor."""

import importlib.util
import sys
import types
from pathlib import Path


def _load_signal_processor():
    if "langchain_openai" not in sys.modules:
        langchain_openai = types.ModuleType("langchain_openai")
        langchain_openai.ChatOpenAI = object
        sys.modules["langchain_openai"] = langchain_openai
    if "tradingagents.utils.logging_init" not in sys.modules:
        logging_init = types.ModuleType("tradingagents.utils.logging_init")

        class _Logger:
            def debug(self, *args, **kwargs):
                pass

            def info(self, *args, **kwargs):
                pass

            def warning(self, *args, **kwargs):
                pass

            def error(self, *args, **kwargs):
                pass

        logging_init.get_logger = lambda *args, **kwargs: _Logger()
        sys.modules["tradingagents.utils.logging_init"] = logging_init
    if "tradingagents.utils.tool_logging" not in sys.modules:
        tool_logging = types.ModuleType("tradingagents.utils.tool_logging")
        tool_logging.log_graph_module = lambda *args, **kwargs: (lambda fn: fn)
        sys.modules["tradingagents.utils.tool_logging"] = tool_logging

    module_path = Path(__file__).resolve().parents[1] / "tradingagents" / "graph" / "signal_processing.py"
    spec = importlib.util.spec_from_file_location("signal_processing_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SignalProcessor


class _Response:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    def __init__(self, content):
        self.content = content

    def invoke(self, messages):
        return _Response(self.content)


def test_process_signal_uses_risk_score_from_source_text_when_json_omits_it():
    SignalProcessor = _load_signal_processor()
    processor = SignalProcessor(_FakeLLM('{"action":"卖出","target_price":18.3,"confidence":0.72,"reasoning":"风险偏高"}'))

    signal = """
    最终建议：卖出。
    目标价格：18.30 元。
    风险评分：0.82。
    风险依据：技术破位、流动性下降、数据质量部分缺失。
    """

    result = processor.process_signal(signal, "002236")

    assert result["risk_score"] == 0.82
    assert result["risk_score_source"] == "source_text"


def test_simple_decision_extracts_percentage_risk_score_from_text():
    SignalProcessor = _load_signal_processor()
    processor = SignalProcessor(_FakeLLM("not json"))

    result = processor._extract_simple_decision("建议持有，目标价 24 元，风险评分：65%，风险等级：高。")

    assert result["risk_score"] == 0.65
    assert result["risk_score_source"] == "source_text"


def test_simple_decision_extracts_markdown_bold_risk_score():
    SignalProcessor = _load_signal_processor()
    processor = SignalProcessor(_FakeLLM("not json"))

    result = processor._extract_simple_decision("**风险评分：** 0.82\n**风险等级：** 极高")

    assert result["risk_score"] == 0.82
    assert result["risk_score_source"] == "source_text"


def test_process_signal_repairs_default_json_risk_score_from_risk_manager_text():
    SignalProcessor = _load_signal_processor()
    processor = SignalProcessor(
        _FakeLLM(
            '{"action":"持有","target_price":null,"confidence":0.7,'
            '"risk_score":0.5,"reasoning":"基于综合分析的投资建议"}'
        )
    )

    signal = """
    risk_management_decision:
    **风险评分：** 0.72
    **风险等级：** 高
    **风险依据：** 技术面破位、数据质量风险、资金持续流出。
    """

    result = processor.process_signal(signal, "002236")

    assert result["risk_score"] == 0.72
    assert result["risk_score_source"] == "risk_management_decision"
    assert result["risk_score_basis"] == "技术面破位、数据质量风险、资金持续流出。"
