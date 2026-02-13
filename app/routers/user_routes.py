from fastapi import APIRouter, Depends, HTTPException
from app.models.user import UserResponse, UserUpdate
from app.middleware.auth import get_current_user
from app.services.mongo import mongo
from bson import ObjectId  # ← import this

router = APIRouter(prefix="/user", tags=["user"])

@router.get("/me", response_model=UserResponse)
async def get_me(user_id: str = Depends(get_current_user)):
    # Convert string to ObjectId for query
    try:
        object_id = ObjectId(user_id)
    except:
        raise HTTPException(400, "Invalid user ID format")

    user = await mongo.users.find_one({"_id": object_id})
    print("Token user_id (string):", user_id)
    print("Found user:", user)

    if not user:
        raise HTTPException(404, "User not found")

    # Prepare response dict (keep _id as string for Pydantic alias)
    response_dict = {
        "_id": str(user["_id"]),  # keep _id key with string value
        "firstName": user["firstName"],
        "lastName": user["lastName"],
        "email": user["email"],
        "credits": user["credits"],
        "created_at": user["created_at"],
        "auth_provider": user["auth_provider"],
        "google_id": user.get("google_id")
    }

    # Do NOT delete _id — Pydantic needs it for alias
    # del user["password"]  # safe to remove password
    response_dict.pop("password", None)  # remove password if exists

    return UserResponse(**response_dict)