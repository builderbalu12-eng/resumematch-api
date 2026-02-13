from fastapi import HTTPException
from app.models.user import UserCreate, LoginRequest, UserResponse
from app.services.mongo import mongo
from app.config import settings
from passlib.context import CryptContext
from datetime import datetime, timedelta
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
            "firstName": user_data.firstName,
            "lastName": user_data.lastName,
            "email": user_data.email,
            "password": hashed_password,
            "credits": 150.0,
            "created_at": datetime.utcnow(),
            "auth_provider": "local",
            "google_id": None
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