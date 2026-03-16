from pydantic import BaseModel, Field
from typing import Optional


class PaymentOrderCreate(BaseModel):
    plan_id: str                                        # fetch amount/currency from plan
    billing_cycle: str = Field("monthly", pattern="^(monthly|yearly)$")
    is_recurring: bool = True
    coupon_code: Optional[str] = None                  # optional discount


class PaymentVerify(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str
