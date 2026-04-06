from datetime import datetime, timezone
from typing import Dict, List

from bson import ObjectId
from fastapi import HTTPException

from app.services.mongo import mongo


def _str_id(doc: dict) -> dict:
    if doc and "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    return doc


class AdminController:

    @staticmethod
    async def get_stats() -> Dict:
        total_users = await mongo.users.count_documents({})
        active_coupons = await mongo.coupons.count_documents({"is_active": True})
        total_features = await mongo.credits_on_features.count_documents({})

        # Sum all user credits
        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$credits"}}}]
        result = await mongo.users.aggregate(pipeline).to_list(length=1)
        total_credits = result[0]["total"] if result else 0.0

        return {
            "status": 200,
            "success": True,
            "data": {
                "total_users": total_users,
                "total_credits_in_system": round(total_credits, 2),
                "active_coupons": active_coupons,
                "total_features": total_features,
            }
        }

    @staticmethod
    async def list_users(skip: int = 0, limit: int = 50) -> Dict:
        cursor = mongo.users.find(
            {},
            {"firstName": 1, "lastName": 1, "email": 1, "credits": 1, "created_at": 1, "auth_provider": 1}
        ).skip(skip).limit(limit).sort("created_at", -1)

        users = await cursor.to_list(length=limit)
        total = await mongo.users.count_documents({})
        users = [_str_id(u) for u in users]

        return {
            "status": 200,
            "success": True,
            "data": {"items": users, "total": total, "skip": skip, "limit": limit}
        }

    @staticmethod
    async def adjust_user_credits(user_id: str, amount: float, reason: str) -> Dict:
        if amount == 0:
            raise HTTPException(400, "Amount cannot be zero")

        user = await mongo.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(404, "User not found")

        new_credits = max(0.0, user.get("credits", 0) + amount)
        await mongo.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"credits": new_credits, "updated_at": datetime.now(timezone.utc)}}
        )

        await mongo.credits_log.insert_one({
            "_id": ObjectId(),
            "user_id": user_id,
            "type": "admin_adjustment",
            "amount": amount,
            "feature": "admin",
            "function_name": "adjust_user_credits",
            "description": reason or "Admin manual adjustment",
            "balance_after": new_credits,
            "created_at": datetime.now(timezone.utc),
        })

        return {
            "status": 200,
            "success": True,
            "message": f"Credits adjusted by {amount}. New balance: {new_credits}",
            "data": {"user_id": user_id, "new_credits": new_credits}
        }

    @staticmethod
    async def list_feature_costs() -> Dict:
        cursor = mongo.credits_on_features.find({}).sort("feature", 1)
        features = await cursor.to_list(length=100)
        features = [_str_id(f) for f in features]
        return {
            "status": 200,
            "success": True,
            "data": features
        }

    @staticmethod
    async def update_feature_cost(feature_name: str, credits_per_unit: float) -> Dict:
        if credits_per_unit < 0:
            raise HTTPException(400, "credits_per_unit cannot be negative")

        result = await mongo.credits_on_features.update_one(
            {"feature": feature_name},
            {"$set": {"credits_per_unit": credits_per_unit, "updated_at": datetime.now(timezone.utc)}}
        )

        if result.matched_count == 0:
            raise HTTPException(404, f"Feature '{feature_name}' not found")

        return {
            "status": 200,
            "success": True,
            "message": f"Feature '{feature_name}' cost updated to {credits_per_unit}"
        }

    @staticmethod
    async def get_user_credits_log(user_id: str) -> Dict:
        features_list = await mongo.credits_on_features.find(
            {}, {"feature": 1, "display_name": 1}
        ).to_list(100)
        display_name_map = {f["feature"]: f.get("display_name", f["feature"]) for f in features_list}

        logs = await mongo.credits_log.find(
            {"user_id": user_id, "feature": {"$ne": "generic"}}
        ).sort("created_at", -1).to_list(length=100)

        for log in logs:
            log.pop("_id", None)
            log["display_name"] = display_name_map.get(log.get("feature", ""), log.get("feature", "Unknown"))

        return {"status": 200, "success": True, "data": logs}

    @staticmethod
    async def get_user_billing(user_id: str) -> Dict:
        # Current active (or most recent) subscription
        subscription = await mongo.subscriptions.find_one(
            {"user_id": user_id},
            sort=[("created_at", -1)],
        )
        if subscription:
            subscription.pop("_id", None)

        # Full billing history, newest first
        history = await mongo.billing_history.find(
            {"user_id": user_id}
        ).sort("payment_date", -1).to_list(length=100)
        for h in history:
            h.pop("_id", None)

        return {
            "status": 200,
            "success": True,
            "data": {
                "subscription": subscription,
                "billing_history": history,
            },
        }

    @staticmethod
    async def get_coupon_usage(coupon_id: str) -> Dict:
        logs = await mongo.coupon_usage_log.find(
            {"coupon_id": coupon_id}
        ).sort("created_at", -1).to_list(length=200)
        for log in logs:
            user = await mongo.users.find_one(
                {"_id": ObjectId(log["user_id"])}, {"email": 1, "firstName": 1}
            )
            log["user_email"] = user.get("email", "unknown") if user else "unknown"
            log["user_name"]  = user.get("firstName", "") if user else ""
            log.pop("_id", None)
        return {"status": 200, "success": True, "data": logs}

    @staticmethod
    async def list_coupons(skip: int = 0, limit: int = 50, active_only: bool = False) -> Dict:
        query = {"is_active": True} if active_only else {}
        cursor = mongo.coupons.find(query).skip(skip).limit(limit).sort("created_at", -1)
        coupons = await cursor.to_list(length=limit)
        total = await mongo.coupons.count_documents(query)
        coupons = [_str_id(c) for c in coupons]
        return {
            "status": 200,
            "success": True,
            "data": {"items": coupons, "total": total, "skip": skip, "limit": limit}
        }
