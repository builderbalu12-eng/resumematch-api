# app/services/credits_service.py
from app.services.mongo import mongo
from bson import ObjectId
from datetime import datetime
from fastapi import HTTPException
from typing import Tuple


class CreditsService:
    @staticmethod
    async def add_credits(
        user_id: str,
        credits: float,
        transaction_id: str,
        amount_paid: float,
        currency: str
    ) -> float:
        """
        Add credits after successful payment.
        Prevents double-crediting using transaction_id.
        """
        # Prevent double crediting
        existing = await mongo.payment_logs.find_one({"transaction_id": transaction_id})
        if existing:
            print(f"Transaction {transaction_id} already processed → skipping")
            return existing.get("new_credits", 0.0)

        user = await mongo.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(404, "User not found")

        current_credits = user.get("credits", 0.0)
        new_credits = current_credits + credits

        await mongo.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "credits": new_credits,
                    "updated_at": datetime.utcnow()
                }
            }
        )

        await mongo.payment_logs.insert_one({
            "user_id": user_id,
            "transaction_id": transaction_id,
            "amount_paid": amount_paid,
            "currency": currency,
            "credits_added": credits,
            "status": "succeeded",
            "created_at": datetime.utcnow(),
            "type": "add"
        })

        return new_credits


    @staticmethod
    async def deduct_credits(
        user_id: str,
        amount: float = 1.0
    ) -> Tuple[bool, str]:
        """
        Deduct credits when using a paid feature (Gemini endpoints).
        Returns (success: bool, message: str)
        """
        user = await mongo.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            return False, "User not found"

        current_credits = user.get("credits", 0.0)

        if current_credits < amount:
            return False, f"Insufficient credits (have {current_credits:.1f}, need {amount:.1f})"

        new_credits = current_credits - amount

        await mongo.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "credits": new_credits,
                    "updated_at": datetime.utcnow()
                }
            }
        )

        await mongo.payment_logs.insert_one({
            "user_id": user_id,
            "credits_deducted": amount,
            "status": "consumed",
            "created_at": datetime.utcnow(),
            "type": "deduct",
            "reason": f"Used {amount} credit(s) for AI feature"
        })

        return True, f"Deducted {amount}. Remaining: {new_credits:.1f}"
    
    @staticmethod
    async def refund_credits(user_id: str, amount: float, reason: str = "Processing failed"):
        user = await mongo.users.find_one({"_id": ObjectId(user_id)})
        if user:
            current = user.get("credits", 0.0)
            new = current + amount
            await mongo.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"credits": new, "updated_at": datetime.utcnow()}}
            )
            await mongo.payment_logs.insert_one({
                "user_id": user_id,
                "credits_refunded": amount,
                "status": "refunded",
                "created_at": datetime.utcnow(),
                "type": "refund",
                "reason": reason
            })