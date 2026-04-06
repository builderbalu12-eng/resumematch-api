from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from bson import ObjectId

from app.dependencies.admin import require_admin
from app.controllers.admin_controller import AdminController
from app.controllers.analytics_controller import AnalyticsController
from app.controllers.payment.coupon_controller import CouponController
from app.models.payment.coupon import CouponCreate
from app.services.mongo import mongo

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
