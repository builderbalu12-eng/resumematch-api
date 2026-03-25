# app/controllers/user_controller.py

from fastapi import HTTPException, status, Depends
from pydantic import BaseModel
from bson import ObjectId
from bson.errors import InvalidId
from passlib.context import CryptContext

from app.models.user import UserResponse, UserUpdate, ChangePasswordRequest
from app.services.mongo import mongo
from app.middleware.auth import get_current_user

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Response Models ───────────────────────────────────
class UserResponseData(BaseModel):
    user: UserResponse


class UserResponseModel(BaseModel):
    status:  int
    success: bool
    message: str
    data:    UserResponseData


class CreditsResponseData(BaseModel):
    credits:      float
    has_payments: bool


class CreditsResponseModel(BaseModel):
    status:  int
    success: bool
    message: str
    data:    CreditsResponseData


class UserController:

    # ── Internal helpers ──────────────────────────────
    @staticmethod
    def _prepare_user_data(user_doc: dict) -> dict:
        if "_id" in user_doc:
            user_doc["_id"] = str(user_doc["_id"])
        if "auth_provider" not in user_doc:
            user_doc["auth_provider"] = "local"
        if "google_id" not in user_doc:
            user_doc["google_id"] = None
        if "telegram_chat_id" not in user_doc:
            user_doc["telegram_chat_id"] = None
        if "telegram_linked" not in user_doc:
            user_doc["telegram_linked"] = False
        if "telegram_link_token" not in user_doc:
            user_doc["telegram_link_token"] = None
        if "has_payments" not in user_doc:
            user_doc["has_payments"] = False      # ✅ default
        return user_doc

    @staticmethod
    def _get_user_query(user_id: str) -> dict:
        try:
            return {"_id": ObjectId(user_id)}
        except (InvalidId, ValueError):
            return {"_id": user_id}

    # ── GET /user/me ──────────────────────────────────
    @staticmethod
    async def get_user(
        user_id:      str,
        current_user: str,
    ) -> UserResponseModel:
        if user_id != current_user:
            raise HTTPException(status_code=403, detail="Not authorized")

        user = await mongo.users.find_one(
            UserController._get_user_query(user_id)
        )
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # ✅ Check if user has made at least one real payment
        payment_count = await mongo.payment_logs.count_documents({
            "user_id": str(user["_id"]),
            "type":    "add"
        })
        user["has_payments"] = payment_count > 0

        user = UserController._prepare_user_data(user)
        return UserResponseModel(
            status=200, success=True,
            message="User retrieved successfully",
            data=UserResponseData(user=UserResponse(**user))
        )

    # ── PATCH /user/me — update name only ─────────────
    @staticmethod
    async def update_user(
        user_id:      str,
        current_user: str,
        user_data:    UserUpdate,
    ) -> UserResponseModel:
        if user_id != current_user:
            raise HTTPException(status_code=403, detail="Not authorized")

        query = UserController._get_user_query(user_id)
        user  = await mongo.users.find_one(query)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        update_data = user_data.dict(exclude_unset=True)
        update_data.pop("email", None)

        if not update_data:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        await mongo.users.update_one(query, {"$set": update_data})

        updated = await mongo.users.find_one(query)

        # ✅ Re-check payments after update too
        payment_count = await mongo.payment_logs.count_documents({
            "user_id": str(updated["_id"]),
            "type":    "add"
        })
        updated["has_payments"] = payment_count > 0

        updated = UserController._prepare_user_data(updated)
        return UserResponseModel(
            status=200, success=True,
            message="Profile updated successfully",
            data=UserResponseData(user=UserResponse(**updated))
        )

    # ── POST /user/me/change-password ─────────────────
    @staticmethod
    async def change_password(
        user_id:      str,
        current_user: str,
        payload:      ChangePasswordRequest,
    ) -> dict:
        if user_id != current_user:
            raise HTTPException(status_code=403, detail="Not authorized")

        query = UserController._get_user_query(user_id)
        user  = await mongo.users.find_one(query)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not user.get("password"):
            raise HTTPException(
                status_code=400,
                detail="Password change not available for Google login accounts"
            )

        if not pwd_context.verify(payload.current_password, user["password"]):
            raise HTTPException(
                status_code=401,
                detail="Current password is incorrect"
            )

        if payload.new_password != payload.confirm_password:
            raise HTTPException(
                status_code=400,
                detail="New password and confirm password do not match"
            )

        if len(payload.new_password) < 6:
            raise HTTPException(
                status_code=400,
                detail="New password must be at least 6 characters"
            )

        hashed = pwd_context.hash(payload.new_password)
        await mongo.users.update_one(
            query,
            {"$set": {"password": hashed}}
        )

        return {"success": True, "message": "Password changed successfully"}

    # ── GET /user/me/credits ───────────────────────────
    @staticmethod
    async def get_user_credits(
        user_id:      str,
        current_user: str,
    ) -> CreditsResponseModel:
        if user_id != current_user:
            raise HTTPException(status_code=403, detail="Not authorized")

        user = await mongo.users.find_one(
            UserController._get_user_query(user_id),
            {"credits": 1}
        )
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # ✅ Check payments
        payment_count = await mongo.payment_logs.count_documents({
            "user_id": str(user["_id"]),
            "type":    "add"
        })

        return CreditsResponseModel(
            status=200, success=True,
            message="Credits retrieved successfully",
            data=CreditsResponseData(
                credits=user["credits"],
                has_payments=payment_count > 0
            )
        )
