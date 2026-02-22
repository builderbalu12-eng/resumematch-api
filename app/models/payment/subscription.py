from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SubscriptionCreate(BaseModel):
    plan_id: str
    user_id: str


class SubscriptionUpdate(BaseModel):
    status: Optional[str] = None  # active, cancelled, paused
    pause_until: Optional[datetime] = None


class SubscriptionOut(BaseModel):
    id: str = Field(..., alias="_id")
    user_id: str
    plan_id: str
    razorpay_subscription_id: str
    status: str = "created"
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True