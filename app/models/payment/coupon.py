from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class CouponCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=20)
    discount_percent: Optional[float] = Field(None, ge=0, le=100)
    discount_amount: Optional[float] = Field(None, ge=0)
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True
    applicable_to_plans: Optional[List[str]] = None  # plan_ids or empty for all
    applicable_to_domains: Optional[List[str]] = None  # e.g. ["example.com"] for org discount


class CouponUpdate(BaseModel):
    discount_percent: Optional[float] = None
    discount_amount: Optional[float] = None
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None
    is_active: Optional[bool] = None
    applicable_to_plans: Optional[List[str]] = None
    applicable_to_domains: Optional[List[str]] = None


class CouponOut(CouponCreate):
    id: str = Field(..., alias="_id")
    uses_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True