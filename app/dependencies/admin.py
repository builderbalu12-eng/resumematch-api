from fastapi import Depends, HTTPException
from bson import ObjectId

from app.config import settings
from app.services.mongo import mongo
from app.middleware.auth import get_current_user


async def require_admin(current_user_id: str = Depends(get_current_user)) -> str:
    """FastAPI dependency — raises 403 if the caller is not an admin email."""
    user = await mongo.users.find_one({"_id": ObjectId(current_user_id)})
    email = user.get("email", "").strip().lower() if user else ""
    if email not in settings.admin_email_set:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user_id
