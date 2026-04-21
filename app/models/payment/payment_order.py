from pydantic import BaseModel, Field
from typing import Optional


class PaymentOrderCreate(BaseModel):
    plan_id: str
    billing_cycle: str = Field("monthly", pattern="^(monthly|yearly)$")
    is_recurring: bool = True
    coupon_code: Optional[str] = None


class PaymentVerify(BaseModel):
    cashfree_order_id: str  # Cashfree order_id returned from create_order
