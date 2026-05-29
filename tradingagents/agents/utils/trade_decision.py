from typing import Optional

from pydantic import BaseModel, Field


class TradeDecision(BaseModel):
    """Structured trade decision output model for Risk Manager."""

    action: str = Field(
        description="买入、持有、卖出或弃权之一"
    )
    target_price: float = Field(
        description="目标价格数值"
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

    # 新增字段（Optional，向后兼容）
    stop_loss: Optional[float] = Field(
        default=None,
        description="止损价格"
    )
    risk_reward_ratio: Optional[float] = Field(
        default=None,
        description="盈亏比（预期收益/预期损失），如 2.0 表示收益是风险的2倍"
    )
    position_size: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="建议仓位比例（占总资金的0-1比例）"
    )
    horizon: Optional[str] = Field(
        default=None,
        description="预期持有期（如'5个交易日'、'20个交易日'、'60个交易日'）"
    )
    invalidation: Optional[str] = Field(
        default=None,
        description="失效条件：什么信号出现就推翻当前判断"
    )
