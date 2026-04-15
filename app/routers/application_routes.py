from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime

from app.middleware.auth import get_current_user
from app.models.application import ApplicationRecordCreate
from app.services.mongo import mongo

router = APIRouter(tags=["applications"])


@router.post("/applications", response_model=dict)
async def create_application(
    record: ApplicationRecordCreate,
    current_user: str = Depends(get_current_user),
):
    doc = {**record.dict(), "userId": current_user, "createdAt": datetime.utcnow()}
    result = await mongo.applications.insert_one(doc)
    return {"id": str(result.inserted_id), "message": "saved"}


@router.get("/applications", response_model=dict)
async def list_applications(
    current_user: str = Depends(get_current_user),
):
    cursor = mongo.applications.find({"userId": current_user}).sort("createdAt", -1).limit(100)
    docs = await cursor.to_list(100)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"applications": docs}


@router.delete("/applications/{app_id}", response_model=dict)
async def delete_application(
    app_id: str,
    current_user: str = Depends(get_current_user),
):
    try:
        oid = ObjectId(app_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid application ID")
    await mongo.applications.delete_one({"_id": oid, "userId": current_user})
    return {"message": "deleted"}
