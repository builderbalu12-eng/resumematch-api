# app/models/payment/payment_order.py
from pydantic import BaseModel, Field
from typing import Optional


class PaymentOrderCreate(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    credits_to_add: float = Field(..., gt=0)
    receipt: Optional[str] = None


class PaymentVerify(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str