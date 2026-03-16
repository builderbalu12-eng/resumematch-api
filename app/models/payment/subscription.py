from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SubscriptionCreate(BaseModel):
    plan_id: str
    billing_cycle: str = Field("monthly", pattern="^(monthly|yearly)$")
    is_recurring: bool = True
    coupon_code: Optional[str] = None          # single field, backend auto-detects type


class SubscriptionUpdate(BaseModel):
    status: Optional[str] = None               # active | cancelled | paused | past_due
    renewal_date: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None


class SubscriptionOut(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    plan_id: str
    plan_name: Optional[str] = None            # denormalized for quick display
    amount_paid: Optional[float] = None        # after coupon discount
    currency: Optional[str] = "INR"
    billing_cycle: str
    is_recurring: bool
    razorpay_subscription_id: Optional[str] = None   # None for Free plan
    stripe_subscription_id: Optional[str] = None     # future Stripe support
    status: str = "created"
    start_date: Optional[datetime] = None
    renewal_date: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    coupon_id: Optional[str] = None            # applied coupon reference
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
