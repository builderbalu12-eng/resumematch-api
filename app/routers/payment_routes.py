from fastapi import APIRouter, Depends, Request, HTTPException, Query, Body
from typing import Dict, Optional
from app.middleware.auth import get_current_user
from app.controllers.payment.plan_controller import PlanController
from app.controllers.payment.subscription_controller import SubscriptionController
from app.controllers.payment.coupon_controller import CouponController
from app.controllers.payment.payment_controller import PaymentController
from app.models.payment.plan import PlanCreate, PlanUpdate
from app.models.payment.subscription import SubscriptionCreate, SubscriptionUpdate
from app.models.payment.coupon import CouponCreate, CouponUpdate
from app.models.payment.billing_history import BillingHistoryOut
from app.models.payment import PaymentOrderCreate, PaymentVerify
from app.services.mongo import mongo
from app.services.payment.webhook_service import WebhookService
from bson import ObjectId
from datetime import datetime


router = APIRouter(prefix="/payments", tags=["payments"])


# ────────────────────────────────────────────────
# Plans
# ────────────────────────────────────────────────

@router.post("/subscription-plans", response_model=Dict)
async def create_plan(
    data: PlanCreate,
    current_user: str = Depends(get_current_user)
):
    return await PlanController.create_plan(data, current_user)


# AFTER — make it public
@router.get("/subscription-plans", response_model=Dict)
async def list_plans(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True),
):
    return await PlanController.list_plans(skip, limit, active_only, current_user=None)


@router.get("/subscription-plans/{plan_id}", response_model=Dict)
async def get_plan(
    plan_id: str,
    current_user: str = Depends(get_current_user)
):
    return await PlanController.get_plan(plan_id, current_user)


@router.put("/subscription-plans/{plan_id}", response_model=Dict)
async def update_plan(
    plan_id: str,
    data: PlanUpdate,
    current_user: str = Depends(get_current_user)
):
    return await PlanController.update_plan(plan_id, data, current_user)


@router.delete("/subscription-plans/{plan_id}", response_model=Dict)
async def delete_plan(
    plan_id: str,
    current_user: str = Depends(get_current_user)
):
    return await PlanController.delete_plan(plan_id, current_user)


# ────────────────────────────────────────────────
# Subscriptions
# ────────────────────────────────────────────────

@router.post("/subscriptions", response_model=Dict)
async def create_subscription(
    data: SubscriptionCreate,
    current_user: str = Depends(get_current_user)
):
    return await SubscriptionController.create_subscription(data, current_user)


@router.get("/subscriptions", response_model=Dict)
async def list_subscriptions(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: str = Depends(get_current_user)
):
    return await SubscriptionController.list_subscriptions(skip, limit, current_user)


@router.get("/subscriptions/{subscription_id}", response_model=Dict)
async def get_subscription(
    subscription_id: str,
    current_user: str = Depends(get_current_user)
):
    return await SubscriptionController.get_subscription(subscription_id, current_user)


@router.put("/subscriptions/{subscription_id}", response_model=Dict)
async def update_subscription(
    subscription_id: str,
    data: SubscriptionUpdate,
    current_user: str = Depends(get_current_user)
):
    return await SubscriptionController.update_subscription(subscription_id, data, current_user)


@router.delete("/subscriptions/{subscription_id}", response_model=Dict)
async def cancel_subscription(
    subscription_id: str,
    current_user: str = Depends(get_current_user)
):
    return await SubscriptionController.cancel_subscription(subscription_id, current_user)


# ────────────────────────────────────────────────
# One-time Payments (Order + Verify)
# ────────────────────────────────────────────────

@router.post("/create-order", response_model=Dict)
async def create_order(
    data: PaymentOrderCreate,
    current_user: str = Depends(get_current_user)
):
    return await PaymentController.create_order(data, current_user)


@router.post("/verify", response_model=Dict)
async def verify_payment(
    data: PaymentVerify,
    current_user: str = Depends(get_current_user)
):
    return await PaymentController.verify_payment(data, current_user)


# ────────────────────────────────────────────────
# Coupons
# ────────────────────────────────────────────────

@router.post("/coupons", response_model=Dict)
async def create_coupon(
    data: CouponCreate,
    current_user: str = Depends(get_current_user)
):
    return await CouponController.create_coupon(data, current_user)


@router.get("/coupons", response_model=Dict)
async def list_coupons(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True),
    current_user: str = Depends(get_current_user)
):
    return await CouponController.list_coupons(skip, limit, active_only, current_user)


@router.get("/coupons/{coupon_id}", response_model=Dict)
async def get_coupon(
    coupon_id: str,
    current_user: str = Depends(get_current_user)
):
    return await CouponController.get_coupon(coupon_id, current_user)


@router.put("/coupons/{coupon_id}", response_model=Dict)
async def update_coupon(
    coupon_id: str,
    data: CouponUpdate,
    current_user: str = Depends(get_current_user)
):
    return await CouponController.update_coupon(coupon_id, data, current_user)


@router.delete("/coupons/{coupon_id}", response_model=Dict)
async def delete_coupon(
    coupon_id: str,
    current_user: str = Depends(get_current_user)
):
    return await CouponController.delete_coupon(coupon_id, current_user)


# ────────────────────────────────────────────────
# Coupon Validate
# ────────────────────────────────────────────────

@router.post("/coupons/validate", response_model=Dict)
async def validate_coupon(
    code: str = Body(..., embed=True),
    plan_id: str = Body(..., embed=True),
    current_user: str = Depends(get_current_user)
):
    user = await mongo.users.find_one({"_id": ObjectId(current_user)})
    user_email = user.get("email", "") if user else ""
    user_domain = user_email.split("@")[-1] if "@" in user_email else ""

    coupon = await mongo.coupons.find_one({"code": code.upper(), "is_active": True})
    if not coupon:
        raise HTTPException(400, "Invalid coupon code")

    if coupon.get("expires_at") and coupon["expires_at"] < datetime.utcnow():
        raise HTTPException(400, "Coupon has expired")

    if coupon.get("max_uses") and coupon.get("uses_count", 0) >= coupon["max_uses"]:
        raise HTTPException(400, "Coupon usage limit reached")

    if coupon.get("applicable_to_plans") and plan_id not in coupon["applicable_to_plans"]:
        raise HTTPException(400, "Coupon is not valid for this plan")

    coupon_type = coupon.get("coupon_type", "individual")

    if coupon_type == "individual":
        if coupon.get("applicable_to_user_id") != current_user:
            raise HTTPException(400, "This coupon is not valid for your account")
    elif coupon_type == "domain":
        if user_domain not in (coupon.get("applicable_to_domains") or []):
            raise HTTPException(400, "This coupon is not valid for your email domain")

    plan = await mongo.plans.find_one({"_id": ObjectId(plan_id)})
    if not plan:
        raise HTTPException(404, "Plan not found")

    original_amount = plan["amount"]
    discount = 0

    if coupon.get("discount_percent"):
        discount = original_amount * (coupon["discount_percent"] / 100)
    elif coupon.get("discount_amount"):
        discount = coupon["discount_amount"]

    discounted_amount = max(original_amount - discount, 0)

    return {
        "status": 200,
        "success": True,
        "message": "Coupon applied successfully",
        "data": {
            "code": code.upper(),
            "coupon_type": coupon_type,
            "original_amount": original_amount,
            "discount": round(discount, 2),
            "discounted_amount": round(discounted_amount, 2),
            "currency": plan.get("currency", "INR")
        }
    }


# ────────────────────────────────────────────────
# Billing History
# ────────────────────────────────────────────────

@router.get("/billing-history", response_model=Dict)
async def get_billing_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: str = Depends(get_current_user)
):
    query = {"user_id": current_user}
    cursor = mongo.billing_history.find(query).skip(skip).limit(limit).sort("payment_date", -1)
    history = await cursor.to_list(length=limit)
    total = await mongo.billing_history.count_documents(query)

    result = []
    for h in history:
        h_safe = h.copy()
        h_safe["_id"] = str(h_safe["_id"])
        result.append(BillingHistoryOut(**h_safe).model_dump(by_alias=True))

    return {
        "status": 200,
        "success": True,
        "message": f"Found {len(result)} billing records",
        "data": {
            "items": result,
            "total": total,
            "skip": skip,
            "limit": limit
        }
    }


# ────────────────────────────────────────────────
# Webhook
# ────────────────────────────────────────────────

@router.post("/webhook", response_model=dict)
async def razorpay_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    return await WebhookService.handle_razorpay_webhook(payload, signature)
