from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class PaymentLogCreate(BaseModel):
    user_id: str
    plan_id: str
    amount: float
    currency: str
    credits_added: float
    razorpay_subscription_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    status: str = "pending"


class PaymentLogOut(PaymentLogCreate):
    id: str = Field(..., alias="_id")
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True