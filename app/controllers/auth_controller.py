import secrets
from fastapi import HTTPException
from app.models.user import UserCreate, LoginRequest, UserResponse
from app.services.mongo import mongo
from app.services.email_service import send_email, _password_reset_html
from app.config import settings
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from jose import jwt
from pydantic import BaseModel
from bson import ObjectId


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthData(BaseModel):
    user: UserResponse
    access_token: str
    token_type: str

class AuthResponse(BaseModel):
    status: int
    success: bool
    message: str
    data: AuthData


class AuthController:
    @staticmethod
    async def register(user_data: UserCreate) -> AuthResponse:
        collection = mongo.users
        if await collection.find_one({"email": user_data.email}):
            raise HTTPException(status_code=400, detail="User with this email already exists")

        hashed_password = pwd_context.hash(user_data.password)

        user_doc = {
            "firstName":  user_data.firstName,
            "lastName":   user_data.lastName,
            "email":      user_data.email,
            "password":   hashed_password,
            "credits":    150.0,
            "created_at": datetime.utcnow(),
            "auth_provider": "local",
            "google_id":  None,

            # ── Telegram fields ───────────────────
            "telegram_chat_id":    None,
            "telegram_linked":     False,
            "telegram_link_token": None,
        }


        result = await collection.insert_one(user_doc)

        # Convert ObjectId to string right after insert
        user_dict = user_doc.copy()
        user_dict["_id"] = str(result.inserted_id)  # ← this line fixes the validation error

        token = jwt.encode(
            {"sub": user_dict["_id"], "email": user_dict["email"], "exp": datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm
        )

        return AuthResponse(
            status=201,
            success=True,
            message="User registered successfully",
            data=AuthData(
                user=UserResponse(**user_dict),
                access_token=token,
                token_type="bearer"
            )
        )

    @staticmethod
    async def login(login_data: LoginRequest) -> AuthResponse:
        collection = mongo.users
        user = await collection.find_one({"email": login_data.email})

        if not user or not pwd_context.verify(login_data.password, user.get("password")):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user_dict = dict(user)
        user_dict["_id"] = str(user["_id"])  # ← convert ObjectId to str

        token = jwt.encode(
            {"sub": user_dict["_id"], "email": user_dict["email"], "exp": datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm
        )

        return AuthResponse(
            status=200,
            success=True,
            message="Login successful",
            data=AuthData(
                user=UserResponse(**user_dict),
                access_token=token,
                token_type="bearer"
            )
        )

    @staticmethod
    async def forgot_password(email: str) -> dict:
        # Always return the same message — don't reveal if email exists
        generic = {"status": 200, "success": True, "message": "If this email is registered, you'll receive a reset link shortly."}

        user = await mongo.users.find_one({"email": email})
        if not user:
            return generic

        # Only local-auth users have a password to reset
        if user.get("auth_provider", "local") != "local":
            return generic

        # Invalidate any existing unused tokens for this email
        await mongo.password_reset_tokens.update_many(
            {"email": email, "used": False},
            {"$set": {"used": True}}
        )

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

        await mongo.password_reset_tokens.insert_one({
            "email": email,
            "token": token,
            "expires_at": expires_at,
            "used": False,
            "created_at": datetime.now(timezone.utc),
        })

        reset_link = f"{settings.frontend_base_url}/reset-password?token={token}"
        try:
            await send_email(
                to_email=email,
                subject="Reset your ResumeMatch password",
                html_body=_password_reset_html(reset_link),
            )
        except Exception as e:
            print(f"[forgot_password] Email send failed: {e}")
            # Don't expose email errors to the client

        return generic

    @staticmethod
    async def reset_password(token: str, new_password: str) -> dict:
        if len(new_password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

        print(f"[reset_password] Looking up token: {token[:20]}...")
        record = await mongo.password_reset_tokens.find_one({"token": token, "used": False})
        print(f"[reset_password] Record found: {record is not None}")
        if not record:
            # Check if token exists but is used/expired
            any_record = await mongo.password_reset_tokens.find_one({"token": token})
            print(f"[reset_password] Token exists (any status): {any_record is not None}, used={any_record.get('used') if any_record else 'N/A'}")
            raise HTTPException(status_code=400, detail="Invalid or expired reset link")

        if record["expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Reset link has expired. Please request a new one.")

        hashed = pwd_context.hash(new_password)
        await mongo.users.update_one(
            {"email": record["email"]},
            {"$set": {"password": hashed, "updated_at": datetime.now(timezone.utc)}}
        )
        await mongo.password_reset_tokens.update_one(
            {"_id": record["_id"]},
            {"$set": {"used": True}}
        )

        return {"status": 200, "success": True, "message": "Password reset successfully. You can now log in."}