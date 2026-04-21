from fastapi import HTTPException
from app.config import settings
from app.services.payment import cashfree_service
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
        """Create a Cashfree order for a plan (one-time or subscription)."""

        # 1. Fetch plan
        plan = await mongo.plans.find_one({"_id": ObjectId(data.plan_id)})
        if not plan:
            raise HTTPException(404, "Plan not found")
        if not plan.get("is_active"):
            raise HTTPException(400, "Plan is not active")

        # 2. Fetch user email for Cashfree customer_details
        user = await mongo.users.find_one({"_id": ObjectId(current_user)})
        if not user:
            raise HTTPException(404, "User not found")

        amount = plan["amount"]
        coupon_id = None

        # 3. Apply coupon
        if data.coupon_code:
            user_email = user.get("email", "")
            user_domain = user_email.split("@")[-1] if "@" in user_email else ""

            coupon = await mongo.coupons.find_one({
                "code": data.coupon_code.upper(),
                "is_active": True,
            })
            if not coupon:
                raise HTTPException(400, "Invalid coupon code")
            if coupon.get("expires_at") and coupon["expires_at"] < datetime.utcnow():
                raise HTTPException(400, "Coupon has expired")
            if coupon.get("max_uses") and coupon.get("uses_count", 0) >= coupon["max_uses"]:
                raise HTTPException(400, "Coupon usage limit reached")
            if coupon.get("applicable_to_plans") and data.plan_id not in coupon["applicable_to_plans"]:
                raise HTTPException(400, "Coupon not valid for this plan")

            coupon_type = coupon.get("coupon_type", "individual")
            if coupon_type == "individual" and coupon.get("applicable_to_user_id") != current_user:
                raise HTTPException(400, "Coupon not valid for your account")
            elif coupon_type == "domain" and user_domain not in (coupon.get("applicable_to_domains") or []):
                raise HTTPException(400, "Coupon not valid for your email domain")

            if coupon.get("discount_percent"):
                amount = max(amount - (amount * coupon["discount_percent"] / 100), 0)
            elif coupon.get("discount_amount"):
                amount = max(amount - coupon["discount_amount"], 0)

            coupon_id = str(coupon["_id"])
            await mongo.coupons.update_one({"_id": coupon["_id"]}, {"$inc": {"uses_count": 1}})
            await mongo.coupon_usage_log.insert_one({
                "coupon_id": coupon_id,
                "coupon_code": coupon["code"],
                "user_id": current_user,
                "plan_id": data.plan_id,
                "discount_applied": plan["amount"] - amount,
                "payment_type": "order",
                "created_at": datetime.utcnow(),
            })

        # 4. Create Cashfree order
        cf_order_id = f"ord_{current_user[:12]}_{int(datetime.utcnow().timestamp())}"
        cf_order = await cashfree_service.create_order(
            order_id=cf_order_id,
            amount=amount,
            currency=plan.get("currency", "INR"),
            customer_id=current_user,
            customer_email=user.get("email", "user@example.com"),
            tags={
                "user_id": current_user,
                "plan_id": str(plan["_id"]),
                "billing_cycle": getattr(data, "billing_cycle", "monthly"),
            },
        )

        return {
            "status": 200,
            "success": True,
            "message": "Payment order created",
            "data": {
                "payment_session_id": cf_order["payment_session_id"],
                "cashfree_order_id": cf_order["order_id"],
                "amount": cf_order["order_amount"],
                "currency": cf_order["order_currency"],
                "plan_name": plan["plan_name"],
                "description": plan.get("description") or plan["plan_name"],
                "coupon_id": coupon_id,
            },
        }

    @staticmethod
    async def verify_payment(data: PaymentVerify, current_user: str) -> Dict:
        """Verify payment by fetching order status from Cashfree."""

        cf_order = await cashfree_service.get_order(data.cashfree_order_id)
        order_status = cf_order.get("order_status")

        if order_status != "PAID":
            raise HTTPException(400, f"Payment not completed. Status: {order_status}")

        tags = cf_order.get("order_tags") or {}
        plan_id = tags.get("plan_id")
        billing_cycle = tags.get("billing_cycle", "monthly")
        amount_paid = float(cf_order.get("order_amount", 0))

        plan = None
        if plan_id:
            try:
                plan = await mongo.plans.find_one({"_id": ObjectId(plan_id)})
            except Exception:
                pass

        renewal_date = datetime.utcnow() + (
            timedelta(days=365) if billing_cycle == "yearly" else timedelta(days=30)
        )

        return {
            "status": 200,
            "success": True,
            "message": "Payment verified successfully",
            "data": {
                "plan_name": plan["plan_name"] if plan else None,
                "amount_paid": amount_paid,
                "renewal_date": renewal_date.isoformat(),
            },
        }
