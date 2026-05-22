from pydantic import BaseModel, Field


class TradeDecision(BaseModel):
    """Structured trade decision output model for Risk Manager."""

    action: str = Field(
        description="买入、持有或卖出之一"
    )
    target_price: float = Field(
        description="目标价格数值，必须提供具体数值，不允许为null"
    )
    confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="0-1之间的置信度"
    )
    risk_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="0-1之间的风险评分"
    )
    reasoning: str = Field(
        description="决策理由的中文摘要"
    )