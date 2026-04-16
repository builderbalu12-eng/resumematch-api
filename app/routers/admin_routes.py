from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from bson import ObjectId

from app.dependencies.admin import require_admin
from app.controllers.admin_controller import AdminController
from app.controllers.analytics_controller import AnalyticsController
from app.controllers.payment.coupon_controller import CouponController
from app.controllers.payment.plan_controller import PlanController
from app.models.payment.coupon import CouponCreate
from app.models.payment.plan import PlanCreate, PlanUpdate
from app.services.mongo import mongo
from app.config import settings
from app.services.gemini_config_service import (
    get_gemini_config,
    save_gemini_config,
    AVAILABLE_MODELS,
)
from app.services.claude_config_service import (
    get_claude_config,
    save_claude_config,
    AVAILABLE_MODELS as CLAUDE_MODELS,
)
from app.services.ai_provider_service import (
    get_active_provider,
    set_active_provider,
)
from app.services.admin_settings_service import get_default_credits, set_default_credits, get_app_config, set_app_config

router = APIRouter(prefix="/admin", tags=["admin"])


class AdjustCreditsBody(BaseModel):
    amount: float
    reason: str = ""


class UpdateFeatureCostBody(BaseModel):
    credits_per_unit: float


class SetDefaultCreditsBody(BaseModel):
    credits: float


class SocialLinksUpdate(BaseModel):
    twitter: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    facebook: Optional[str] = None
    instagram: Optional[str] = None
    youtube: Optional[str] = None


class CollaboratorItem(BaseModel):
    name: str
    role: str = ""
    image_url: str = ""


class AppConfigUpdate(BaseModel):
    app_name: Optional[str] = None
    support_email: Optional[str] = None
    logo_url: Optional[str] = None
    social_links: Optional[SocialLinksUpdate] = None
    collaborators: Optional[List[CollaboratorItem]] = None


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


class ClaudeConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class ActiveProviderUpdate(BaseModel):
    provider: str  # "gemini" | "claude"


# ── Gemini model list (original route kept + new named route) ─

@router.get("/resources/models")
async def list_gemini_models(admin: str = Depends(require_admin)):
    """Return the list of available Gemini models (legacy route, kept for compatibility)."""
    return {"data": AVAILABLE_MODELS}


@router.get("/resources/models/gemini")
async def list_gemini_models_named(admin: str = Depends(require_admin)):
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


# ── Claude Resource ───────────────────────────────────────────

@router.get("/resources/models/claude")
async def list_claude_models(admin: str = Depends(require_admin)):
    """Return the list of available Claude models."""
    return {"data": CLAUDE_MODELS}


@router.get("/resources/claude")
async def get_claude_resource(admin: str = Depends(require_admin)):
    """Return current Claude config + today's usage count from credits_log."""
    cfg = await get_claude_config()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = await mongo.credits_log.count_documents({
        "type": "deduction",
        "provider": "claude",
        "created_at": {"$gte": today_start},
    })

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    pipeline = [
        {"$match": {"type": "deduction", "provider": "claude", "created_at": {"$gte": thirty_days_ago}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]
    history_cursor = mongo.credits_log.aggregate(pipeline)
    history = [{"date": d["_id"], "count": d["count"]} async for d in history_cursor]

    return {
        "data": {
            "api_key_masked": cfg["api_key"][:8] + "•" * 20 if cfg["api_key"] else "",
            "api_key_full":   cfg["api_key"],
            "model":          cfg["model"],
            "temperature":    cfg["temperature"],
            "max_tokens":     cfg["max_tokens"],
            "updated_at":     cfg["updated_at"].isoformat() if cfg["updated_at"] else None,
            "updated_by":     cfg["updated_by"],
            "today_usage":    today_count,
            "usage_history":  history,
            "available_models": CLAUDE_MODELS,
        }
    }


@router.patch("/resources/claude")
async def update_claude_config(
    body: ClaudeConfigUpdate,
    admin: str = Depends(require_admin),
):
    """Save new Claude API key / model / settings. Takes effect immediately."""
    update = body.model_dump(exclude_none=True)
    if not update:
        raise HTTPException(400, "No fields provided to update")
    await save_claude_config(update, admin_email=admin)
    return {"success": True, "message": "Claude config updated and applied immediately."}


# ── Active AI Provider ────────────────────────────────────────

@router.get("/resources/active-provider")
async def get_active_ai_provider(admin: str = Depends(require_admin)):
    """Return which AI provider is currently active (gemini or claude)."""
    provider = await get_active_provider()
    return {"data": {"provider": provider}}


@router.patch("/resources/active-provider")
async def update_active_ai_provider(
    body: ActiveProviderUpdate,
    admin: str = Depends(require_admin),
):
    """Switch the active AI provider. Takes effect immediately for all AI features."""
    if body.provider not in ("gemini", "claude"):
        raise HTTPException(400, "provider must be 'gemini' or 'claude'")
    await set_active_provider(body.provider, admin_email=admin)
    return {
        "success":  True,
        "provider": body.provider,
        "message":  f"Switched to {body.provider}. All AI features now use {body.provider.capitalize()}.",
    }


@router.get("/resources/jsearch")
async def get_jsearch_resource(admin: str = Depends(require_admin)):
    """Return JSearch / RapidAPI quota usage for today + 30-day history."""
    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    thirty_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    doc = await mongo.rapidapi_usage_log.find_one({"date": today})

    history_cursor = mongo.rapidapi_usage_log.find(
        {"date": {"$gte": thirty_ago}},
        sort=[("date", 1)],
    )
    history = [
        {"date": h["date"], "calls": h.get("calls_today", 0)}
        async for h in history_cursor
    ]

    key = settings.jsearch_api_key
    return {
        "data": {
            "api_key_masked":     (key[:8] + "•" * 20) if key else "",
            "requests_limit":     doc["requests_limit"]     if doc else 200,
            "requests_remaining": doc["requests_remaining"] if doc else 200,
            "calls_today":        doc["calls_today"]        if doc else 0,
            "requests_reset":     doc.get("requests_reset") if doc else None,
            "last_updated":       doc["last_updated"].isoformat() if doc and doc.get("last_updated") else None,
            "usage_history":      history,
        }
    }


@router.get("/resources/jsearch/daily-feed")
async def get_jsearch_daily_feed(
    date: Optional[str] = None,   # YYYY-MM-DD, defaults to today
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: str = Depends(require_admin),
):
    """Return daily_job_feed entries for a given date with job details."""
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Parse date boundaries in UTC
    day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    day_end   = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)

    total = await mongo.daily_job_feed.count_documents({
        "created_at": {"$gte": day_start, "$lte": day_end}
    })
    skip  = (page - 1) * limit

    cursor = mongo.daily_job_feed.find(
        {"created_at": {"$gte": day_start, "$lte": day_end}},
        sort=[("created_at", -1)],
    ).skip(skip).limit(limit)

    # Look up user emails for display
    entries = []
    async for doc in cursor:
        user_id = doc.get("user_id", "")
        # Fetch user email for display (mask it)
        user_email = ""
        try:
            from bson import ObjectId
            user = await mongo.users.find_one({"_id": ObjectId(user_id)}, {"email": 1})
            if user:
                e = user.get("email", "")
                # mask: show first 3 chars + *** + @domain
                parts = e.split("@")
                user_email = parts[0][:3] + "***@" + parts[1] if len(parts) == 2 else e[:6] + "***"
        except Exception:
            user_email = user_id[:8] + "..."

        jobs = doc.get("jobs", [])
        # Count jobs by source site
        site_counts: dict = {}
        for j in jobs:
            s = j.get("site", "unknown")
            site_counts[s] = site_counts.get(s, 0) + 1

        entries.append({
            "user_email":    user_email,
            "search_term":   doc.get("search_term", ""),
            "location":      doc.get("location", ""),
            "total_jobs":    len(jobs),
            "site_breakdown": site_counts,
            "created_at":    doc["created_at"].isoformat() if doc.get("created_at") else "",
            "jobs": [
                {
                    "title":       j.get("title", ""),
                    "company":     j.get("company", ""),
                    "location":    j.get("location", ""),
                    "site":        j.get("site", ""),
                    "fit_score":   j.get("fit_score", 0),
                    "job_url":     j.get("job_url", ""),
                    "is_remote":   j.get("is_remote"),
                    "description_summary": j.get("description_summary", ""),
                }
                for j in jobs
            ],
        })

    return {
        "data": {
            "date":        date,
            "total":       total,
            "page":        page,
            "total_pages": max(1, (total + limit - 1) // limit),
            "entries":     entries,
        }
    }


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


# ── Default Signup Credits ────────────────────────────────────

@router.get("/settings/default-credits")
async def get_signup_credits(admin: str = Depends(require_admin)):
    """Get the default credits given to every new user on signup."""
    value = await get_default_credits()
    return {"success": True, "default_credits": value}


@router.patch("/settings/default-credits")
async def update_signup_credits(
    body: SetDefaultCreditsBody,
    admin: str = Depends(require_admin),
):
    """Update the default credits given to every new user on signup."""
    if body.credits < 0:
        raise HTTPException(400, "Credits cannot be negative")
    value = await set_default_credits(body.credits)
    return {"success": True, "default_credits": value}


# ── Plans / Pricing ───────────────────────────────────────────

@router.get("/plans")
async def list_all_plans(
    active_only: bool = Query(False),
    admin: str = Depends(require_admin),
):
    """List all plans (including inactive) for admin editing."""
    return await PlanController.list_plans(skip=0, limit=100, active_only=active_only, current_user=admin)


@router.post("/plans")
async def create_plan(
    data: PlanCreate,
    admin: str = Depends(require_admin),
):
    """Create a new plan (creates Razorpay plan for paid recurring plans)."""
    return await PlanController.create_plan(data, admin)


@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    data: PlanUpdate,
    admin: str = Depends(require_admin),
):
    """Update plan fields: name, amount, credits_per_cycle, points, is_active."""
    return await PlanController.update_plan(plan_id, data, admin)


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: str,
    admin: str = Depends(require_admin),
):
    """Delete a plan (hard delete — use PATCH is_active=false to soft-disable)."""
    return await PlanController.delete_plan(plan_id, admin)


# ── App Config (Branding) ─────────────────────────────────────

@router.get("/settings/app-config")
async def get_app_config_admin(admin: str = Depends(require_admin)):
    """Get app branding config (app name, support email, logo, social links, collaborators)."""
    return {"data": await get_app_config()}


@router.patch("/settings/app-config")
async def update_app_config_admin(
    body: AppConfigUpdate,
    admin: str = Depends(require_admin),
):
    """Update app branding config (partial update)."""
    updates = body.model_dump(exclude_unset=True)
    # Convert SocialLinksUpdate to plain dict if present
    if "social_links" in updates and updates["social_links"] is not None:
        updates["social_links"] = {k: v for k, v in updates["social_links"].items() if v is not None}
    # Convert CollaboratorItem list to plain dicts if present
    if "collaborators" in updates and updates["collaborators"] is not None:
        updates["collaborators"] = [
            {"name": c["name"], "role": c.get("role", ""), "image_url": c.get("image_url", "")}
            for c in updates["collaborators"]
        ]
    result = await set_app_config(updates)
    return {"data": result}
