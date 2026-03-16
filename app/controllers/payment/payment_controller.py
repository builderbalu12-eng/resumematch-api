from fastapi import HTTPException
from app.config import settings
from app.services.payment.razorpay_service import razorpay_service
from app.services.mongo import mongo
from app.models.payment import PaymentOrderCreate, PaymentVerify
from bson import ObjectId
from datetime import datetime, timedelta
from typing import Dict, Optional


def normalize_id(doc: Dict) -> Dict:
    if doc and "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    return doc


class PaymentController:

    @staticmethod
    async def create_order(data: PaymentOrderCreate, current_user: str) -> Dict:
        """Create a one-time Razorpay order for a plan"""

        # 1. Fetch plan
        plan = await mongo.plans.find_one({"_id": ObjectId(data.plan_id)})
        if not plan:
            raise HTTPException(404, "Plan not found")
        if not plan.get("is_active"):
            raise HTTPException(400, "Plan is not active")

        amount = plan["amount"]
        coupon_id = None

        # 2. Apply coupon if provided
        if data.coupon_code:
            user = await mongo.users.find_one({"_id": ObjectId(current_user)})
            user_email = user.get("email", "") if user else ""
            user_domain = user_email.split("@")[-1] if "@" in user_email else ""

            coupon = await mongo.coupons.find_one({
                "code": data.coupon_code.upper(),
                "is_active": True
            })

            if not coupon:
                raise HTTPException(400, "Invalid coupon code")

            if coupon.get("expires_at") and coupon["expires_at"] < datetime.utcnow():
                raise HTTPException(400, "Coupon has expired")

            if coupon.get("max_uses") and coupon.get("uses_count", 0) >= coupon["max_uses"]:
                raise HTTPException(400, "Coupon usage limit reached")

            if coupon.get("applicable_to_plans") and data.plan_id not in coupon["applicable_to_plans"]:
                raise HTTPException(400, "Coupon is not valid for this plan")

            coupon_type = coupon.get("coupon_type", "individual")

            if coupon_type == "individual":
                if coupon.get("applicable_to_user_id") != current_user:
                    raise HTTPException(400, "Coupon not valid for your account")
            elif coupon_type == "domain":
                if user_domain not in (coupon.get("applicable_to_domains") or []):
                    raise HTTPException(400, "Coupon not valid for your email domain")

            if coupon.get("discount_percent"):
                amount = max(amount - (amount * coupon["discount_percent"] / 100), 0)
            elif coupon.get("discount_amount"):
                amount = max(amount - coupon["discount_amount"], 0)

            coupon_id = str(coupon["_id"])
            await mongo.coupons.update_one(
                {"_id": coupon["_id"]},
                {"$inc": {"uses_count": 1}}
            )

        # 3. Create Razorpay order
        order = razorpay_service.create_order(
            amount=amount,
            currency=plan.get("currency", "INR"),
            receipt=f"order_{current_user}_{int(datetime.utcnow().timestamp())}",
            user_id=current_user,
            plan_id=str(plan["_id"]),
            billing_cycle=getattr(data, "billing_cycle", "monthly")
        )

        return {
            "status": 200,
            "success": True,
            "message": "Payment order created",
            "data": {
                "key": settings.razorpay_key_id,
                "amount": order["amount"],
                "currency": order["currency"],
                "order_id": order["id"],
                "plan_name": plan["plan_name"],
                "description": plan.get("description") or plan["plan_name"],
                "coupon_id": coupon_id
            }
        }

    @staticmethod
    async def verify_payment(data: PaymentVerify, current_user: str) -> Dict:
        """Verify signature only — webhook handles credits & billing history"""

        # 1. Verify signature
        is_valid = razorpay_service.verify_signature(
            data.razorpay_payment_id,
            data.razorpay_order_id,
            data.razorpay_signature
        )
        if not is_valid:
            raise HTTPException(400, "Invalid payment signature")

        # 2. Fetch order for plan info to return to frontend
        try:
            order = razorpay_service.client.order.fetch(data.razorpay_order_id)
        except Exception as e:
            raise HTTPException(500, f"Could not fetch order: {e}")

        notes = order.get("notes", {})
        plan_id = notes.get("plan_id")
        billing_cycle = notes.get("billing_cycle", "monthly")
        amount_paid = order["amount"] / 100

        plan = None
        if plan_id:
            try:
                plan = await mongo.plans.find_one({"_id": ObjectId(plan_id)})
            except Exception:
                pass

        renewal_date = datetime.utcnow() + (
            timedelta(days=365) if billing_cycle == "yearly" else timedelta(days=30)
        )

        # ✅ Webhook handles credits + billing history + active_plan update
        return {
            "status": 200,
            "success": True,
            "message": "Payment verified successfully",
            "data": {
                "plan_name": plan["plan_name"] if plan else None,
                "amount_paid": amount_paid,
                "renewal_date": renewal_date.isoformat()
            }
        }
