from app.services.razorpay_service import razorpay_service
from app.services.credits_service import CreditsService
from app.services.mongo import mongo
from bson import ObjectId
from datetime import datetime
from fastapi import HTTPException
from typing import Dict


class PaymentService:
    @staticmethod
    async def create_plan(data: Dict):
        plan_data = {
            "period": data["period"],
            "interval": data["interval"],
            "item": {
                "name": data["plan_name"],
                "amount": int(data["amount"] * 100),
                "currency": data["currency"].upper(),
                "description": data.get("description")
            }
        }

        razorpay_plan = razorpay_service.create_plan(plan_data)

        await mongo.plans.insert_one({
            "_id": ObjectId(),
            "plan_name": data["plan_name"],
            "amount": data["amount"],
            "currency": data["currency"],
            "period": data["period"],
            "interval": data["interval"],
            "credits_per_cycle": data["credits_per_cycle"],
            "description": data.get("description"),
            "razorpay_plan_id": razorpay_plan["id"],
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })

        return {"plan_id": razorpay_plan["id"]}

    @staticmethod
    async def create_subscription(data: Dict):
        sub_data = {
            "plan_id": data["plan_id"],
            "total_count": data.get("total_count", 0),
            "customer_notify": 1
        }

        razorpay_sub = razorpay_service.create_subscription(sub_data)

        await mongo.subscriptions.insert_one({
            "_id": ObjectId(),
            "user_id": data["user_id"],
            "plan_id": data["plan_id"],
            "razorpay_subscription_id": razorpay_sub["id"],
            "status": razorpay_sub["status"],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })

        return {
            "subscription_id": razorpay_sub["id"],
            "short_url": razorpay_sub["short_url"]
        }

    @staticmethod
    async def apply_coupon(code: str, amount: float, plan_id: str, user_domain: str = None):
        coupon = await mongo.coupons.find_one({"code": code.upper(), "is_active": True})
        if not coupon:
            return amount, None

        if coupon.get("expires_at") and coupon["expires_at"] < datetime.utcnow():
            return amount, None

        if coupon.get("applicable_to_plans") and plan_id not in coupon["applicable_to_plans"]:
            return amount, None

        if coupon.get("applicable_to_domains") and user_domain not in coupon["applicable_to_domains"]:
            return amount, None

        if coupon["discount_percent"]:
            discount = amount * (coupon["discount_percent"] / 100)
        elif coupon["discount_amount"]:
            discount = coupon["discount_amount"]
        else:
            discount = 0

        new_amount = max(amount - discount, 0)

        await mongo.coupons.update_one(
            {"code": code.upper()},
            {"$inc": {"uses_count": 1}}
        )

        return new_amount, coupon["_id"]