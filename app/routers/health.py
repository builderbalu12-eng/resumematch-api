from fastapi import APIRouter, HTTPException
from app.services.mongo import mongo

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.environment,
        "api_version": "0.1.0",
    }


@router.get("/db")
async def check_db():
    try:
        collections = await mongo.db.list_collection_names()
        return {
            "connected": True,
            "database": mongo.db.name,
            "collections": collections
        }
    except Exception as e:
        raise HTTPException(500, detail=f"DB error: {str(e)}")