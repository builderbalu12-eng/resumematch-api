from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class CouponCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=20)
    coupon_type: str = Field("individual", pattern="^(individual|domain)$")  # backend auto-detects on validate
    applicable_to_user_id: Optional[str] = None        # for individual coupon
    applicable_to_domains: Optional[List[str]] = None  # for domain coupon e.g. ["university.edu"]
    discount_percent: Optional[float] = Field(None, ge=0, le=100)
    discount_amount: Optional[float] = Field(None, ge=0)
    applicable_to_plans: Optional[List[str]] = None    # plan_ids, empty = all plans
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True


class CouponUpdate(BaseModel):
    discount_percent: Optional[float] = None
    discount_amount: Optional[float] = None
    applicable_to_user_id: Optional[str] = None
    applicable_to_domains: Optional[List[str]] = None
    applicable_to_plans: Optional[List[str]] = None
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None
    is_active: Optional[bool] = None


class CouponOut(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    code: str
    coupon_type: str                                    # individual | domain
    applicable_to_user_id: Optional[str] = None
    applicable_to_domains: Optional[List[str]] = None
    discount_percent: Optional[float] = None
    discount_amount: Optional[float] = None
    applicable_to_plans: Optional[List[str]] = None
    max_uses: Optional[int] = None
    uses_count: int = 0
    expires_at: Optional[datetime] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
