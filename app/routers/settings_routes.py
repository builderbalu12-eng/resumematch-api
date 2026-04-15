from fastapi import APIRouter
from app.services.admin_settings_service import get_app_config

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/app-config")
async def get_public_app_config():
    """Public endpoint — no auth required. Frontend reads this on load."""
    return {"data": await get_app_config()}
