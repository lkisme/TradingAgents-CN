import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError


MODULE_PATH = Path(__file__).resolve().parents[1] / "tradingagents" / "agents" / "utils" / "trade_decision.py"
spec = importlib.util.spec_from_file_location("trade_decision", MODULE_PATH)
trade_decision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trade_decision)
TradeDecision = trade_decision.TradeDecision


def test_trade_decision_requires_risk_score():
    with pytest.raises(ValidationError):
        TradeDecision(
            action="持有",
            target_price=10.0,
            confidence=0.7,
            reasoning="风险评分缺失时不能静默使用0.5",
        )


def test_trade_decision_accepts_explicit_risk_score():
    decision = TradeDecision(
        action="持有",
        target_price=10.0,
        confidence=0.7,
        risk_score=0.72,
        reasoning="明确给出风险评分",
    )

    assert decision.risk_score == 0.72
