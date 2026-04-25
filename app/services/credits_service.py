# app/services/credits_service.py
import contextvars
import logging
from app.services.mongo import mongo
from bson import ObjectId
from datetime import datetime
from fastapi import HTTPException
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Tracks the credits_log _id of the most recent deduction in this request,
# so the AI call layer can update it with real input/output token counts via
# CreditsService.commit_ai_tokens() once the model response returns.
_current_log_id_var: "contextvars.ContextVar[Optional[ObjectId]]" = (
    contextvars.ContextVar("credits_current_log_id", default=None)
)


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
        existing = await mongo.payment_logs.find_one({"transaction_id": transaction_id})
        if existing:
            print(f"Transaction {transaction_id} already processed → skipping")
            return existing.get("new_credits", 0.0)

        user = await mongo.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(404, "User not found")

        current_credits = user.get("credits", 0.0)
        new_credits     = current_credits + credits

        await mongo.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "credits":    new_credits,
                    "updated_at": datetime.utcnow()
                }
            }
        )

        await mongo.payment_logs.insert_one({
            "user_id":        user_id,
            "transaction_id": transaction_id,
            "amount_paid":    amount_paid,
            "currency":       currency,
            "credits_added":  credits,
            "status":         "succeeded",
            "created_at":     datetime.utcnow(),
            "type":           "add",
            "new_credits":    new_credits,
        })

        return new_credits

    @staticmethod
    async def deduct_credits(
        user_id: str,
        amount:  float = 1.0,
        feature: str = "generic",
    ) -> Tuple[bool, str]:
        """
        Deduct credits when using a paid feature.
        Updates users + credits_log.
        """
        from app.services.ai_provider_service import get_active_provider_sync

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
                    "credits":    new_credits,
                    "updated_at": datetime.utcnow()
                }
            }
        )

        from app.services.ai_provider_service import reset_request_tokens

        log_doc = {
            "user_id":       user_id,
            "type":          "deduction",
            "amount":        amount,
            "feature":       feature,
            "function_name": "deduct_credits",
            "description":   f"Credits deducted for {feature}",
            "balance_after": new_credits,
            "provider":      get_active_provider_sync(),
            "input_tokens":  0,
            "output_tokens": 0,
            "created_at":    datetime.utcnow(),
        }
        result = await mongo.credits_log.insert_one(log_doc)
        # Stash log_id + reset token accumulator so call_claude() tokens land here.
        _current_log_id_var.set(result.inserted_id)
        reset_request_tokens()

        return True, f"Deducted {amount}. Remaining: {new_credits:.1f}"

    @staticmethod
    async def refund_credits(user_id: str, amount: float, reason: str = "Processing failed"):
        user = await mongo.users.find_one({"_id": ObjectId(user_id)})
        if user:
            current = user.get("credits", 0.0)
            new     = current + amount
            await mongo.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"credits": new, "updated_at": datetime.utcnow()}}
            )
            await mongo.credits_log.insert_one({
                "user_id":       user_id,
                "type":          "refund",
                "amount":        amount,
                "feature":       "refund",
                "description":   reason,
                "balance_after": new,
                "created_at":    datetime.utcnow(),
            })

    @staticmethod
    async def commit_ai_tokens() -> None:
        """
        Persist the tokens accumulated by call_claude() during this request
        onto the credits_log entry created by the matching deduct_credits().
        Safe to call when no AI call happened — it's a no-op then.
        """
        from app.services.ai_provider_service import get_request_tokens, reset_request_tokens

        log_id = _current_log_id_var.get()
        tokens = get_request_tokens()
        if log_id is None:
            return
        if not tokens["input"] and not tokens["output"]:
            return
        try:
            await mongo.credits_log.update_one(
                {"_id": log_id},
                {"$set": {
                    "input_tokens":  tokens["input"],
                    "output_tokens": tokens["output"],
                }},
            )
        except Exception as e:
            logger.warning(f"commit_ai_tokens failed for log {log_id}: {e}")
        finally:
            _current_log_id_var.set(None)
            reset_request_tokens()

    @staticmethod
    async def log_deduction(
        user_id:       str,
        amount:        float,
        feature:       str = "unknown",
        function_name: str = "unknown",
        description:   str = "",
        input_tokens:  int = 0,
        output_tokens: int = 0,
        provider:      str = None,
    ) -> None:
        from app.services.ai_provider_service import get_active_provider_sync

        user = await mongo.users.find_one(
            {"_id": ObjectId(user_id)},
            {"credits": 1}
        )
        balance_after = user.get("credits", 0) if user else 0

        await mongo.credits_log.insert_one({
            "_id":           ObjectId(),
            "user_id":       user_id,
            "type":          "deduction",
            "amount":        amount,
            "feature":       feature,
            "function_name": function_name,
            "description":   description,
            "balance_after": balance_after,
            "provider":      provider or get_active_provider_sync(),
            "input_tokens":  input_tokens or 0,
            "output_tokens": output_tokens or 0,
            "created_at":    datetime.utcnow(),
        })

    @staticmethod
    async def get_feature_cost(feature: str) -> float:
        doc = await mongo.credits_on_features.find_one(
            {"feature": feature, "is_active": True}
        )
        if not doc:
            return 0.0
        return float(doc.get("credits_per_unit", 0))
