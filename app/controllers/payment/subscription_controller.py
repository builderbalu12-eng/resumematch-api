from fastapi import HTTPException
from app.services.payment.razorpay_service import razorpay_service
from app.services.mongo import mongo
from app.models.payment.subscription import SubscriptionCreate, SubscriptionUpdate, SubscriptionOut
from bson import ObjectId
from datetime import datetime
from typing import Dict, List, Optional
from app.config import settings  # ← make sure this is imported


class SubscriptionController:


    @staticmethod
    async def create_subscription(data: SubscriptionCreate, current_user: str = None) -> Dict:
        sub_data = {
            "plan_id": data.plan_id,
            "total_count": 12,
            "customer_notify": 1,
            # Do NOT put callback_url here yet
        }

        razorpay_sub = razorpay_service.create_subscription(sub_data)

        # Now razorpay_sub exists → safe to use
        # callback_url = f"{settings.payment_success_url}?sub_id={razorpay_sub['id']}&user_id={current_user}"
        callback_url = settings.payment_success_url,

        # Optional: If you want to update the subscription with callback_url after creation
        # (Razorpay allows updating some fields post-creation in some cases, but usually better to set at create time)

        # But simplest: just include it in the response for frontend to handle if needed
        # (most common pattern: frontend gets short_url and redirects itself)

        doc = {
            "_id": ObjectId(),
            "user_id": current_user,
            "plan_id": data.plan_id,
            "razorpay_subscription_id": razorpay_sub["id"],
            "status": razorpay_sub["status"],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        await mongo.subscriptions.insert_one(doc)

        return {
            "subscription_id": razorpay_sub["id"],
            "short_url": razorpay_sub.get("short_url"),
            "auth_link": razorpay_sub.get("auth_link"),
            "callback_url": callback_url   # ← optional: return it so frontend knows where user will land
        }
    @staticmethod
    async def get_subscription(subscription_id: str, current_user: str = None) -> Dict:
        doc = await mongo.subscriptions.find_one({"_id": ObjectId(subscription_id)})
        if not doc:
            raise HTTPException(404, "Subscription not found")

        doc_safe = doc.copy()
        if "_id" in doc_safe:
            doc_safe["_id"] = str(doc_safe["_id"])

        return SubscriptionOut(**doc_safe).model_dump(by_alias=True)

    @staticmethod
    async def list_subscriptions(
        skip: int = 0,
        limit: int = 20,
        current_user: str = None
    ) -> Dict:
        query = {"user_id": current_user} if current_user else {}

        # FIX: ensure skip and limit are integers
        skip = int(skip)
        limit = int(limit)

        cursor = mongo.subscriptions.find(query).skip(skip).limit(limit).sort("created_at", -1)
        subs = await cursor.to_list(length=limit)
        total = await mongo.subscriptions.count_documents(query)

        result = []
        for s in subs:
            s_safe = s.copy()
            if "_id" in s_safe:
                s_safe["_id"] = str(s_safe["_id"])
            result.append(SubscriptionOut(**s_safe).model_dump(by_alias=True))

        return {
            "status": 200,
            "success": True,   # ← FIXED: capital T
            "message": f"Found {len(result)} subscriptions",
            "data": {
                "items": result,
                "total": total,
                "skip": skip,
                "limit": limit
            }
        }

    @staticmethod
    async def update_subscription(subscription_id: str, data: SubscriptionUpdate, current_user: str = None) -> Dict:
        update_dict = data.model_dump(exclude_unset=True)
        if not update_dict:
            raise HTTPException(400, "No fields to update")

        update_dict["updated_at"] = datetime.utcnow()

        result = await mongo.subscriptions.update_one(
            {"_id": ObjectId(subscription_id)},
            {"$set": update_dict}
        )

        if result.modified_count == 0:
            raise HTTPException(404, "Subscription not found or no changes")

        updated = await mongo.subscriptions.find_one({"_id": ObjectId(subscription_id)})

        updated_safe = updated.copy()
        if "_id" in updated_safe:
            updated_safe["_id"] = str(updated_safe["_id"])

        return SubscriptionOut(**updated_safe).model_dump(by_alias=True)

    @staticmethod
    async def cancel_subscription(subscription_id: str) -> Dict:
        doc = await mongo.subscriptions.find_one({"_id": ObjectId(subscription_id)})
        if not doc:
            raise HTTPException(404, "Subscription not found")

        razorpay_service.cancel_subscription(doc["razorpay_subscription_id"])

        await mongo.subscriptions.update_one(
            {"_id": ObjectId(subscription_id)},
            {"$set": {"status": "cancelled", "updated_at": datetime.utcnow()}}
        )

        return {"message": "Subscription cancelled"}