from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Any, Dict

from app.models.user import UserResponse, UserUpdate, ChangePasswordRequest
from app.controllers.user_controller import (
    UserController,
    UserResponseModel,
    CreditsResponseModel,
)
from app.services.credits_service import CreditsService
from app.middleware.auth import get_current_user
from app.services.mongo import mongo


router = APIRouter(prefix="/user", tags=["User"])


def _extract_user_id(current_user: Any) -> str:
    if isinstance(current_user, str):
        return current_user
    elif isinstance(current_user, dict):
        return str(
            current_user.get("_id")
            or current_user.get("id")
            or current_user.get("user_id")
            or ""
        )
    return str(current_user)


# ─────────────────────────────────────────────────────
# GET /api/user/me
# ─────────────────────────────────────────────────────
@router.get(
    "/me",
    response_model=UserResponseModel,
    summary="Get current user profile",
)
async def get_me(
    current_user: Any = Depends(get_current_user),
):
    user_id = _extract_user_id(current_user)
    return await UserController.get_user(user_id, user_id)


# ─────────────────────────────────────────────────────
# PATCH /api/user/me
# ─────────────────────────────────────────────────────
@router.patch(
    "/me",
    response_model=UserResponseModel,
    summary="Update profile — firstName and lastName only. Email cannot be changed.",
)
async def update_me(
    user_data:    UserUpdate,
    current_user: Any = Depends(get_current_user),
):
    user_id = _extract_user_id(current_user)
    return await UserController.update_user(user_id, user_id, user_data)


# ─────────────────────────────────────────────────────
# POST /api/user/me/change-password
# ─────────────────────────────────────────────────────
@router.post(
    "/me/change-password",
    summary="Change password — local auth users only",
)
async def change_password(
    payload:      ChangePasswordRequest,
    current_user: Any = Depends(get_current_user),
):
    user_id = _extract_user_id(current_user)
    return await UserController.change_password(user_id, user_id, payload)


# ─────────────────────────────────────────────────────
# GET /api/user/me/credits
# ─────────────────────────────────────────────────────
@router.get(
    "/me/credits",
    response_model=CreditsResponseModel,
    summary="Get current user credits balance",
)
async def get_credits(
    current_user: Any = Depends(get_current_user),
):
    user_id = _extract_user_id(current_user)
    return await UserController.get_user_credits(user_id, user_id)


# ─────────────────────────────────────────────────────
# GET /api/user/feature-cost/{feature}
# e.g. GET /api/user/feature-cost/find_leads
# ─────────────────────────────────────────────────────
@router.get(
    "/me/credits/history",
    response_model=Dict,
    summary="Get current user credits deduction history",
)
async def get_credits_history(
    skip:  int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    current_user: Any = Depends(get_current_user),
):
    user_id = _extract_user_id(current_user)

    features_list = await mongo.credits_on_features.find(
        {}, {"feature": 1, "display_name": 1}
    ).to_list(length=100)
    display_name_map = {f["feature"]: f.get("display_name", f["feature"]) for f in features_list}

    query = {"user_id": user_id, "feature": {"$ne": "generic"}}
    logs = await mongo.credits_log.find(
        query
    ).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)

    for log in logs:
        log.pop("_id", None)
        log["display_name"] = display_name_map.get(log.get("feature", ""), log.get("feature", "Unknown"))

    total = await mongo.credits_log.count_documents(query)
    return {"status": 200, "success": True, "data": {"items": logs, "total": total}}


@router.get(
    "/feature-cost/{feature}",
    response_model=Dict,
    summary="Get credit cost for a specific feature",
)
async def get_feature_cost(
    feature: str,
    current_user: Any = Depends(get_current_user),
):
    cost = await CreditsService.get_feature_cost(feature)
    return {
        "success":      True,
        "feature":      feature,
        "cost_per_unit": int(cost)
    }
