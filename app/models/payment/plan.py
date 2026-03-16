from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class PlanCreate(BaseModel):
    plan_name: str = Field(..., min_length=1, max_length=100)
    amount: float = Field(..., ge=0)
    currency: str = Field("INR", min_length=3, max_length=3)
    is_recurring: bool = True
    billing_cycle: str = Field("monthly", pattern="^(monthly|yearly)$")
    credits_per_cycle: float = Field(0, ge=0)   # ← ADD THIS
    points: Optional[List[str]] = None
    description: Optional[str] = None
    is_active: bool = True


class PlanUpdate(BaseModel):
    plan_name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    is_recurring: Optional[bool] = None
    billing_cycle: Optional[str] = None
    credits_per_cycle: Optional[float] = None   # ← ADD THIS
    points: Optional[List[str]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class PlanOut(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    plan_name: str
    amount: float
    currency: str
    is_recurring: bool
    billing_cycle: str
    credits_per_cycle: float = 0                # ← ADD THIS
    points: Optional[List[str]] = None
    description: Optional[str] = None
    razorpay_plan_id: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
