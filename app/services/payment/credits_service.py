from app.services.mongo import mongo
from bson import ObjectId
from datetime import datetime
from fastapi import HTTPException


class CreditsService:
    @staticmethod
    async def add_credits(user_id: str, credits: float, transaction_id: str, amount_paid: float, currency: str):
        user = await mongo.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(404, "User not found")

        new_credits = user.get("credits", 0) + credits

        await mongo.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "credits": new_credits,
                "updated_at": datetime.utcnow()
            }}
        )

        await mongo.payment_logs.insert_one({
            "user_id": user_id,
            "transaction_id": transaction_id,
            "amount_paid": amount_paid,
            "currency": currency,
            "credits_added": credits,
            "status": "succeeded",
            "created_at": datetime.utcnow()
        })

        return new_credits

    @staticmethod
    async def deduct_credits(user_id: str, credits: float, reason: str):
        user = await mongo.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(404, "User not found")

        current_credits = user.get("credits", 0)
        if current_credits < credits:
            raise HTTPException(400, "Insufficient credits")

        new_credits = current_credits - credits

        await mongo.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "credits": new_credits,
                "updated_at": datetime.utcnow()
            }}
        )

        await mongo.payment_logs.insert_one({
            "user_id": user_id,
            "reason": reason,
            "credits_deducted": credits,
            "status": "deducted",
            "created_at": datetime.utcnow()
        })

        return new_credits