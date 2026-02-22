from fastapi import APIRouter, Depends, Request, HTTPException, Query
from typing import Optional
from app.middleware.auth import get_current_user
from app.controllers.payment.plan_controller import PlanController
from app.controllers.payment.subscription_controller import SubscriptionController
from app.controllers.payment.coupon_controller import CouponController
from app.controllers.payment.payment_controller import PaymentController
from app.models.payment.plan import PlanCreate, PlanUpdate, PlanOut
from app.models.payment.subscription import SubscriptionCreate, SubscriptionUpdate, SubscriptionOut
from app.models.payment.coupon import CouponCreate, CouponUpdate, CouponOut
from app.models.payment.payment_log import PaymentLogOut
from app.models.payment import PaymentOrderCreate, PaymentVerify
from typing import Any, Dict, Optional, List  # ← ADD THIS LINE


router = APIRouter(prefix="/payments", tags=["payments"])

# ────────────────────────────────────────────────
# Plans (Subscription Plans CRUD)
# ────────────────────────────────────────────────

@router.post("/subscription-plans", response_model=Dict)
async def create_plan(
    data: PlanCreate,
    current_user: str = Depends(get_current_user)
):
    return await PlanController.create_plan(data, current_user)


@router.get("/subscription-plans", response_model=Dict)
async def list_plans(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True),
    current_user: str = Depends(get_current_user)
):
    return await PlanController.list_plans(skip, limit, active_only, current_user)


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
# Subscriptions (User Subscriptions CRUD)
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
# Payment Logs (History)
# ────────────────────────────────────────────────

@router.get("/logs", response_model=Dict)
async def list_payment_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: str = Depends(get_current_user)
):
    query = {"user_id": current_user}
    cursor = mongo.payment_logs.find(query).skip(skip).limit(limit).sort("created_at", -1)
    logs = await cursor.to_list(length=limit)
    total = await mongo.payment_logs.count_documents(query)

    result = [PaymentLogOut(**log).model_dump(by_alias=True) for log in logs]

    return {
        "items": result,
        "total": total,
        "skip": skip,
        "limit": limit
    }


# ────────────────────────────────────────────────
# Webhook (Razorpay calls this automatically)
# ────────────────────────────────────────────────

@router.post("/webhook", response_model=Dict)
async def razorpay_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("X-Razorpay-Signature")

    if not sig_header:
        raise HTTPException(400, "Missing signature header")

    if not razorpay_service.verify_webhook(payload, sig_header):
        raise HTTPException(400, "Invalid webhook signature")

    return {"status": "received"}