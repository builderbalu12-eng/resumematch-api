from fastapi import HTTPException
from app.services.payment import cashfree_service
from app.services.mongo import mongo
from app.models.payment.subscription import SubscriptionCreate, SubscriptionUpdate, SubscriptionOut
from bson import ObjectId
from datetime import datetime, timedelta
from typing import Dict


def normalize_id(doc: Dict) -> Dict:
    if doc and "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    return doc


class SubscriptionController:

    @staticmethod
    async def create_subscription(data: SubscriptionCreate, current_user: str = None) -> Dict:

        # 1. Fetch plan
        plan = await mongo.plans.find_one({"_id": ObjectId(data.plan_id)})
        if not plan:
            raise HTTPException(404, "Plan not found")
        if not plan.get("is_active"):
            raise HTTPException(400, "Plan is not active")

        # 2. Fetch user
        user = await mongo.users.find_one({"_id": ObjectId(current_user)})
        if not user:
            raise HTTPException(404, "User not found")

        amount = plan["amount"]
        coupon_id = None

        # 3. Apply coupon
        if data.coupon_code:
            user_email = user.get("email", "")
            user_domain = user_email.split("@")[-1] if "@" in user_email else ""

            coupon = await mongo.coupons.find_one({"code": data.coupon_code.upper(), "is_active": True})
            if not coupon:
                raise HTTPException(400, "Invalid coupon code")
            if coupon.get("expires_at") and coupon["expires_at"] < datetime.utcnow():
                raise HTTPException(400, "Coupon has expired")
            if coupon.get("max_uses") and coupon.get("uses_count", 0) >= coupon["max_uses"]:
                raise HTTPException(400, "Coupon usage limit reached")
            if coupon.get("applicable_to_plans") and data.plan_id not in coupon["applicable_to_plans"]:
                raise HTTPException(400, "Coupon is not valid for this plan")

            coupon_type = coupon.get("coupon_type", "individual")
            if coupon_type == "individual" and coupon.get("applicable_to_user_id") != current_user:
                raise HTTPException(400, "This coupon is not valid for your account")
            elif coupon_type == "domain":
                allowed_domains = coupon.get("applicable_to_domains") or []
                if user_domain not in allowed_domains:
                    raise HTTPException(400, "This coupon is not valid for your email domain")

            if coupon.get("discount_percent"):
                discount = amount * (coupon["discount_percent"] / 100)
            elif coupon.get("discount_amount"):
                discount = coupon["discount_amount"]
            else:
                discount = 0

            amount = max(amount - discount, 0)
            coupon_id = str(coupon["_id"])
            await mongo.coupons.update_one({"_id": coupon["_id"]}, {"$inc": {"uses_count": 1}})
            await mongo.coupon_usage_log.insert_one({
                "coupon_id": coupon_id,
                "coupon_code": coupon["code"],
                "user_id": current_user,
                "plan_id": data.plan_id,
                "discount_applied": discount,
                "payment_type": "subscription",
                "created_at": datetime.utcnow(),
            })

        # 4. Renewal date
        if data.billing_cycle == "yearly":
            renewal_date = datetime.utcnow() + timedelta(days=365)
        else:
            renewal_date = datetime.utcnow() + timedelta(days=30)

        # 5. Save subscription as "created" (activated via webhook after payment)
        doc = {
            "_id": ObjectId(),
            "user_id": current_user,
            "plan_id": data.plan_id,
            "plan_name": plan["plan_name"],
            "amount_paid": amount,
            "currency": plan.get("currency", "INR"),
            "billing_cycle": data.billing_cycle,
            "is_recurring": data.is_recurring,
            "cashfree_subscription_id": None,  # set after payment via webhook
            "razorpay_subscription_id": None,
            "stripe_subscription_id": None,
            "status": "created" if plan["amount"] > 0 else "active",
            "start_date": datetime.utcnow(),
            "renewal_date": renewal_date,
            "cancelled_at": None,
            "coupon_id": coupon_id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        await mongo.subscriptions.insert_one(doc)

        # 6. Free plan: activate immediately
        if plan["amount"] == 0:
            await mongo.users.update_one(
                {"_id": ObjectId(current_user)},
                {"$set": {"active_plan": plan["plan_name"], "updated_at": datetime.utcnow()}}
            )
            return {
                "status": 200,
                "success": True,
                "message": "Free plan activated",
                "data": {
                    "subscription_id": str(doc["_id"]),
                    "payment_session_id": None,
                    "cashfree_order_id": None,
                    "plan_name": plan["plan_name"],
                    "amount": 0,
                    "billing_cycle": data.billing_cycle,
                    "renewal_date": renewal_date.isoformat(),
                },
            }

        # 7. Paid plan: create Cashfree order for checkout
        cf_order_id = f"sub_{current_user[:12]}_{int(datetime.utcnow().timestamp())}"
        cf_order = await cashfree_service.create_order(
            order_id=cf_order_id,
            amount=amount,
            currency=plan.get("currency", "INR"),
            customer_id=current_user,
            customer_email=user.get("email", "user@example.com"),
            tags={
                "user_id": current_user,
                "plan_id": str(plan["_id"]),
                "billing_cycle": data.billing_cycle,
                "subscription_id": str(doc["_id"]),
            },
        )

        return {
            "status": 200,
            "success": True,
            "message": "Subscription order created",
            "data": {
                "subscription_id": str(doc["_id"]),
                "payment_session_id": cf_order["payment_session_id"],
                "cashfree_order_id": cf_order["order_id"],
                "plan_name": plan["plan_name"],
                "amount": amount,
                "billing_cycle": data.billing_cycle,
                "renewal_date": renewal_date.isoformat(),
            },
        }

    @staticmethod
    async def get_subscription(subscription_id: str, current_user: str = None) -> Dict:
        doc = await mongo.subscriptions.find_one({"_id": ObjectId(subscription_id)})
        if not doc:
            raise HTTPException(404, "Subscription not found")
        if current_user and doc.get("user_id") != current_user:
            raise HTTPException(403, "Access denied")
        return {
            "status": 200,
            "success": True,
            "data": SubscriptionOut(**normalize_id(doc.copy())).model_dump(by_alias=True),
        }

    @staticmethod
    async def list_subscriptions(skip: int = 0, limit: int = 20, current_user: str = None) -> Dict:
        query = {"user_id": current_user} if current_user else {}
        cursor = mongo.subscriptions.find(query).skip(int(skip)).limit(int(limit)).sort("created_at", -1)
        subs = await cursor.to_list(length=limit)
        total = await mongo.subscriptions.count_documents(query)
        result = [SubscriptionOut(**normalize_id(s.copy())).model_dump(by_alias=True) for s in subs]
        return {
            "status": 200,
            "success": True,
            "message": f"Found {len(result)} subscriptions",
            "data": {"items": result, "total": total, "skip": skip, "limit": limit},
        }

    @staticmethod
    async def update_subscription(subscription_id: str, data: SubscriptionUpdate, current_user: str = None) -> Dict:
        update_dict = data.model_dump(exclude_unset=True)
        if not update_dict:
            raise HTTPException(400, "No fields to update")
        update_dict["updated_at"] = datetime.utcnow()
        result = await mongo.subscriptions.update_one(
            {"_id": ObjectId(subscription_id)}, {"$set": update_dict}
        )
        if result.modified_count == 0:
            raise HTTPException(404, "Subscription not found or no changes")
        updated = await mongo.subscriptions.find_one({"_id": ObjectId(subscription_id)})
        return {
            "status": 200,
            "success": True,
            "data": SubscriptionOut(**normalize_id(updated.copy())).model_dump(by_alias=True),
        }

    @staticmethod
    async def cancel_subscription(subscription_id: str, current_user: str = None) -> Dict:
        doc = await mongo.subscriptions.find_one({"_id": ObjectId(subscription_id)})
        if not doc:
            raise HTTPException(404, "Subscription not found")
        if current_user and doc.get("user_id") != current_user:
            raise HTTPException(403, "Access denied")

        await mongo.subscriptions.update_one(
            {"_id": ObjectId(subscription_id)},
            {"$set": {"status": "cancelled", "cancelled_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
        )

        other_active = await mongo.subscriptions.count_documents({
            "user_id": current_user,
            "status": "active",
            "_id": {"$ne": ObjectId(subscription_id)},
        })
        if current_user and other_active == 0:
            await mongo.users.update_one(
                {"_id": ObjectId(current_user)},
                {"$set": {"active_plan": "Free", "updated_at": datetime.utcnow()}},
            )

        return {"status": 200, "success": True, "message": "Subscription cancelled"}
