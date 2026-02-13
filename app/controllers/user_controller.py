from fastapi import HTTPException
from app.models.user import UserResponse, UserUpdate
from app.services.mongo import mongo
from app.middleware.auth import get_current_user
from pydantic import BaseModel
from bson import ObjectId
from bson.errors import InvalidId

class UserResponseData(BaseModel):
    user: UserResponse

class UserResponseModel(BaseModel):
    status: int
    success: bool
    message: str
    data: UserResponseData

class CreditsResponseData(BaseModel):
    credits: float

class CreditsResponseModel(BaseModel):
    status: int
    success: bool
    message: str
    data: CreditsResponseData

class UserController:
    @staticmethod
    def _prepare_user_data(user_doc: dict) -> dict:
        if "_id" in user_doc:
            if isinstance(user_doc["_id"], ObjectId):
                user_doc["_id"] = str(user_doc["_id"])
            else:
                user_doc["_id"] = str(user_doc["_id"])
        
        if "auth_provider" not in user_doc:
            user_doc["auth_provider"] = "local"
        if "google_id" not in user_doc:
            user_doc["google_id"] = None
            
        return user_doc

    @staticmethod
    def _get_user_query(user_id: str) -> dict:
        try:
            return {"_id": ObjectId(user_id)}
        except (InvalidId, ValueError):
            return {"_id": user_id}

    @staticmethod
    async def get_user(userId: str, current_user: str = Depends(get_current_user)) -> UserResponseModel:
        if userId != current_user:
            raise HTTPException(status_code=403, detail="Not authorized")

        collection = mongo.users
        user_query = UserController._get_user_query(userId)
        user = await collection.find_one(user_query)
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = UserController._prepare_user_data(user)
        
        return UserResponseModel(
            status=200,
            success=True,
            message="User retrieved successfully",
            data=UserResponseData(user=UserResponse(**user))
        )

    @staticmethod
    async def update_user(userId: str, user_data: UserUpdate, current_user: str = Depends(get_current_user)) -> UserResponseModel:
        if userId != current_user:
            raise HTTPException(status_code=403, detail="Not authorized")

        collection = mongo.users
        user_query = UserController._get_user_query(userId)
        user = await collection.find_one(user_query)
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        update_data = user_data.dict(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        if "email" in update_data and update_data["email"] != user["email"]:
            if await collection.find_one({"email": update_data["email"]}):
                raise HTTPException(status_code=400, detail="Email already in use")
        
        await collection.update_one(user_query, {"$set": update_data})
        
        updated_user = await collection.find_one(user_query)
        updated_user = UserController._prepare_user_data(updated_user)
        
        return UserResponseModel(
            status=200,
            success=True,
            message="User updated successfully",
            data=UserResponseData(user=UserResponse(**updated_user))
        )

    @staticmethod
    async def get_user_credits(userId: str, current_user: str = Depends(get_current_user)) -> CreditsResponseModel:
        if userId != current_user:
            raise HTTPException(status_code=403, detail="Not authorized")

        collection = mongo.users
        user_query = UserController._get_user_query(userId)
        user = await collection.find_one(user_query, {"credits": 1})
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return CreditsResponseModel(
            status=200,
            success=True,
            message="Credits retrieved successfully",
            data=CreditsResponseData(credits=user["credits"])
        )