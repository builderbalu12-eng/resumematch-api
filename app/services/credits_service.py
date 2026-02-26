from app.services.mongo import mongo
from bson import ObjectId
from datetime import datetime
from fastapi import HTTPException


class CreditsService:
    @staticmethod
    async def add_credits(user_id: str, credits: float, transaction_id: str, amount_paid: float, currency: str):
        # Prevent double crediting
        existing = await mongo.payment_logs.find_one({"transaction_id": transaction_id})
        if existing:
            print(f"Transaction {transaction_id} already processed → skipping")
            return existing.get("new_credits")  # or raise, depending on policy

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
            "created_at": datetime.utcnow(),
            # optional: "event_type": "webhook" or "manual"
        })

        return new_credits