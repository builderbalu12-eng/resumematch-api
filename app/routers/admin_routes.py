from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from bson import ObjectId

from app.dependencies.admin import require_admin
from app.controllers.admin_controller import AdminController
from app.controllers.analytics_controller import AnalyticsController
from app.controllers.payment.coupon_controller import CouponController
from app.models.payment.coupon import CouponCreate
from app.services.mongo import mongo
from app.services.gemini_config_service import (
    get_gemini_config,
    save_gemini_config,
    AVAILABLE_MODELS,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class AdjustCreditsBody(BaseModel):
    amount: float
    reason: str = ""


class UpdateFeatureCostBody(BaseModel):
    credits_per_unit: float


class AdminCouponCreate(BaseModel):
    code: str
    coupon_type: str = "individual"
    applicable_to_email: Optional[str] = None    # admin enters email; we resolve to user_id
    applicable_to_domains: Optional[List[str]] = None
    discount_percent: Optional[float] = None
    discount_amount: Optional[float] = None
    applicable_to_plans: Optional[List[str]] = None
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True


# ── Stats ────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(admin: str = Depends(require_admin)):
    return await AdminController.get_stats()


# ── Analytics ─────────────────────────────────────────────────

@router.get("/analytics")
async def get_analytics(
    period: str = Query("today", pattern="^(today|7d|30d|90d)$"),
    admin: str = Depends(require_admin),
):
    try:
        return await AnalyticsController.get_overview(period)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Users ────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: str = Depends(require_admin),
):
    return await AdminController.list_users(skip, limit)


@router.get("/users/{user_id}/billing")
async def get_user_billing(
    user_id: str,
    admin: str = Depends(require_admin),
):
    return await AdminController.get_user_billing(user_id)


@router.get("/users/{user_id}/credits-log")
async def get_user_credits_log(
    user_id: str,
    admin: str = Depends(require_admin),
):
    return await AdminController.get_user_credits_log(user_id)


@router.patch("/users/{user_id}/credits")
async def adjust_user_credits(
    user_id: str,
    body: AdjustCreditsBody,
    admin: str = Depends(require_admin),
):
    return await AdminController.adjust_user_credits(user_id, body.amount, body.reason)


# ── Feature Costs ─────────────────────────────────────────────

@router.get("/feature-costs")
async def list_feature_costs(admin: str = Depends(require_admin)):
    return await AdminController.list_feature_costs()


@router.patch("/feature-costs/{feature_name}")
async def update_feature_cost(
    feature_name: str,
    body: UpdateFeatureCostBody,
    admin: str = Depends(require_admin),
):
    return await AdminController.update_feature_cost(feature_name, body.credits_per_unit)


# ── Coupons ───────────────────────────────────────────────────

@router.get("/coupons")
async def list_coupons(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    active_only: bool = Query(False),
    admin: str = Depends(require_admin),
):
    return await AdminController.list_coupons(skip, limit, active_only)


@router.post("/coupons")
async def create_coupon(
    data: AdminCouponCreate,
    admin: str = Depends(require_admin),
):
    # Resolve email → user_id for individual coupons
    user_id = None
    if data.coupon_type == "individual" and data.applicable_to_email:
        user = await mongo.users.find_one({"email": data.applicable_to_email.strip().lower()})
        if not user:
            raise HTTPException(404, f"No user found with email: {data.applicable_to_email}")
        user_id = str(user["_id"])

    coupon_data = CouponCreate(
        code=data.code,
        coupon_type=data.coupon_type,
        applicable_to_user_id=user_id,
        applicable_to_domains=data.applicable_to_domains,
        discount_percent=data.discount_percent,
        discount_amount=data.discount_amount,
        applicable_to_plans=data.applicable_to_plans,
        max_uses=data.max_uses,
        expires_at=data.expires_at,
        is_active=data.is_active,
    )
    return await CouponController.create_coupon(coupon_data, admin)


@router.get("/coupons/{coupon_id}/usage")
async def get_coupon_usage(
    coupon_id: str,
    admin: str = Depends(require_admin),
):
    return await AdminController.get_coupon_usage(coupon_id)


@router.delete("/coupons/{coupon_id}")
async def delete_coupon(
    coupon_id: str,
    admin: str = Depends(require_admin),
):
    return await CouponController.delete_coupon(coupon_id, admin)


# ── Resource Utilization ─────────────────────────────────────

class GeminiConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@router.get("/resources/models")
async def list_gemini_models(admin: str = Depends(require_admin)):
    """Return the list of available Gemini models with free-tier limits."""
    return {"data": AVAILABLE_MODELS}


@router.get("/resources/gemini")
async def get_gemini_resource(admin: str = Depends(require_admin)):
    """Return current Gemini config + today's usage count from credits_log."""
    cfg = await get_gemini_config()

    # Count today's Gemini calls from credits_log (type=deduction)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = await mongo.credits_log.count_documents({
        "type": "deduction",
        "created_at": {"$gte": today_start},
    })

    # 30-day daily usage
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    pipeline = [
        {"$match": {"type": "deduction", "created_at": {"$gte": thirty_days_ago}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]
    history_cursor = mongo.credits_log.aggregate(pipeline)
    history = [{"date": d["_id"], "count": d["count"]} async for d in history_cursor]

    # Find RPD limit for the active model
    model_info = next((m for m in AVAILABLE_MODELS if m["id"] == cfg["model"]), AVAILABLE_MODELS[0])

    return {
        "data": {
            "api_key_masked": cfg["api_key"][:8] + "•" * 20 if cfg["api_key"] else "",
            "api_key_full": cfg["api_key"],   # admin-only endpoint — OK to return
            "model": cfg["model"],
            "temperature": cfg["temperature"],
            "max_tokens": cfg["max_tokens"],
            "updated_at": cfg["updated_at"].isoformat() if cfg["updated_at"] else None,
            "updated_by": cfg["updated_by"],
            "today_usage": today_count,
            "daily_limit": model_info["rpd"],
            "rpm_limit": model_info["rpm"],
            "usage_history": history,
        }
    }


@router.patch("/resources/gemini")
async def update_gemini_config(
    body: GeminiConfigUpdate,
    admin: str = Depends(require_admin),
):
    """Save new Gemini API key / model / settings. Takes effect immediately."""
    update = body.model_dump(exclude_none=True)
    if not update:
        raise HTTPException(400, "No fields provided to update")
    await save_gemini_config(update, admin_email=admin)
    return {"success": True, "message": "Gemini config updated and applied immediately."}


@router.get("/resources/mongodb")
async def get_mongodb_resource(admin: str = Depends(require_admin)):
    """Return MongoDB Atlas storage usage using the existing connection."""
    db = mongo.db
    try:
        stats = await db.command("dbStats")
    except Exception as e:
        raise HTTPException(500, f"Could not fetch DB stats: {e}")

    # Per-collection stats
    collection_names = await db.list_collection_names()
    col_details = []
    for name in sorted(collection_names):
        try:
            cs = await db.command("collStats", name)
            col_details.append({
                "name": name,
                "count": cs.get("count", 0),
                "size_bytes": cs.get("size", 0),
                "storage_bytes": cs.get("storageSize", 0),
                "index_bytes": cs.get("totalIndexSize", 0),
            })
        except Exception:
            col_details.append({"name": name, "count": 0, "size_bytes": 0, "storage_bytes": 0, "index_bytes": 0})

    # Atlas free tier: 512 MB storage cap
    FREE_TIER_BYTES = 512 * 1024 * 1024

    return {
        "data": {
            "db_name": stats.get("db", ""),
            "collections": stats.get("collections", 0),
            "objects": stats.get("objects", 0),
            "data_size_bytes": stats.get("dataSize", 0),
            "storage_size_bytes": stats.get("storageSize", 0),
            "index_size_bytes": stats.get("indexSize", 0),
            "free_tier_limit_bytes": FREE_TIER_BYTES,
            "collection_details": col_details,
        }
    }
