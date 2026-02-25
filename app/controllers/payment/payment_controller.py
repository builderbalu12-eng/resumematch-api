from fastapi import HTTPException
from app.config import settings  # FIXED: missing import
from app.services.payment.razorpay_service import razorpay_service
from app.services.mongo import mongo
from app.services.credits_service import CreditsService
from app.services.mongo import mongo
from app.models.payment import PaymentOrderCreate, PaymentVerify
from bson import ObjectId
from datetime import datetime
from typing import Dict, Any


def normalize_id(doc: Dict) -> Dict:
    """Convert MongoDB _id to string for Pydantic"""
    if doc and "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    return doc


class PaymentController:

    @staticmethod
    async def create_order(data: PaymentOrderCreate, current_user: str) -> Dict:
        order = razorpay_service.create_order(
            amount=data.amount,
            currency=data.currency,
            credits=data.credits_to_add,
            receipt=data.receipt
        )

        return {
            "status": 200,
            "success": True,  # FIXED: True, not true
            "message": "Payment order created",
            "data": {
                "key": settings.razorpay_key_id,
                "amount": order["amount"],
                "currency": order["currency"],
                "order_id": order["id"],
                "description": f"{data.credits_to_add} Credits"
            }
        }

    @staticmethod
    async def verify_payment(data: PaymentVerify, current_user: str) -> Dict:
        is_valid = razorpay_service.verify_signature(
            data.razorpay_payment_id,
            data.razorpay_order_id,
            data.razorpay_signature
        )

        if not is_valid:
            raise HTTPException(400, "Invalid payment signature")

        order = razorpay_service.client.order.fetch(data.razorpay_order_id)
        credits_added = float(order["notes"].get("credits", 0))
        amount_paid = order["amount"] / 100
        currency = order["currency"]

        new_credits = await CreditsService.add_credits(
            user_id=current_user,
            credits=credits_added,
            transaction_id=data.razorpay_payment_id,
            amount_paid=amount_paid,
            currency=currency
        )

        return {
            "status": 200,
            "success": True,  # FIXED: True, not true
            "message": "Payment verified and credits added",
            "data": {"new_credits": new_credits}
        }

    @staticmethod
    async def apply_coupon_to_order(
        code: str,
        amount: float,
        plan_id: str,
        user_domain: str = None
    ) -> Dict:
        coupon = await mongo.coupons.find_one({"code": code.upper(), "is_active": True})
        if not coupon:
            return {"discounted_amount": amount, "coupon_id": None, "message": "Invalid coupon"}

        if coupon.get("expires_at") and coupon["expires_at"] < datetime.utcnow():
            return {"discounted_amount": amount, "coupon_id": None, "message": "Coupon expired"}

        if coupon.get("applicable_to_plans") and plan_id not in coupon["applicable_to_plans"]:
            return {"discounted_amount": amount, "coupon_id": None, "message": "Coupon not applicable to this plan"}

        if coupon.get("applicable_to_domains") and user_domain not in coupon["applicable_to_domains"]:
            return {"discounted_amount": amount, "coupon_id": None, "message": "Coupon not applicable to your domain"}

        if coupon["discount_percent"]:
            discount = amount * (coupon["discount_percent"] / 100)
        elif coupon["discount_amount"]:
            discount = coupon["discount_amount"]
        else:
            discount = 0

        discounted_amount = max(amount - discount, 0)

        await mongo.coupons.update_one(
            {"code": code.upper()},
            {"$inc": {"uses_count": 1}}
        )

        return {
            "discounted_amount": discounted_amount,
            "coupon_id": str(coupon["_id"]),
            "message": "Coupon applied successfully"
        }