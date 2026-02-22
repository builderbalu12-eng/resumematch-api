from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class PlanCreate(BaseModel):
    plan_name: str = Field(..., min_length=1, max_length=100)
    amount: float = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    period: str = Field(..., pattern="^(daily|weekly|monthly|yearly)$")
    interval: int = Field(..., ge=1)
    credits_per_cycle: float = Field(..., gt=0)
    description: Optional[str] = None
    is_active: bool = True
    applicable_to: Optional[List[str]] = None  # e.g. ["org_domain1.com"] for organization discounts


class PlanUpdate(BaseModel):
    plan_name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    period: Optional[str] = None
    interval: Optional[int] = None
    credits_per_cycle: Optional[float] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    applicable_to: Optional[List[str]] = None


class PlanOut(PlanCreate):
    id: str = Field(..., alias="_id")
    razorpay_plan_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True