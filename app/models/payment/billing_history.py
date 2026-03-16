from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class BillingHistoryOut(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    plan_id: Optional[str] = None
    plan_name: Optional[str] = None
    amount: float
    currency: str = "INR"
    payment_status: str                   # succeeded | failed | pending | refunded
    payment_provider: str                 # razorpay | stripe
    payment_id: str                       # razorpay payment_id or stripe charge_id
    invoice_url: Optional[str] = None     # hosted invoice or short_url
    subscription_id: Optional[str] = None
    is_recurring: bool = True
    is_parallel: bool = False             # True if user has 2+ active subs at same time
    subscription_start: Optional[datetime] = None
    renewal_date: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    payment_date: datetime
    created_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
