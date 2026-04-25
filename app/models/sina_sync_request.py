#!/usr/bin/env python3
"""
新浪 K 线同步请求模型
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class SinaSyncRequest(BaseModel):
    """新浪 K 线同步请求"""
    symbols: Optional[List[str]] = Field(
        default=None,
        description="股票代码列表，为空时自动同步所有不完整股票"
    )
    datalen: int = Field(
        default=1023,
        ge=1,
        le=1023,
        description="数据长度，最大 1023（约 4 年）"
    )