from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class InvoiceCreate(BaseModel):
    user_id: str
    subscription_id: str
    amount: float
    currency: str
    credits_added: float
    razorpay_invoice_id: str
    status: str = "pending"


class InvoiceOut(InvoiceCreate):
    id: str = Field(..., alias="_id")
    invoice_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True