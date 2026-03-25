from fastapi import APIRouter, Depends, HTTPException
from typing import Any, Dict

from app.models.user import UserResponse, UserUpdate, ChangePasswordRequest
from app.controllers.user_controller import (
    UserController,
    UserResponseModel,
    CreditsResponseModel,
)
from app.services.credits_service import CreditsService
from app.middleware.auth import get_current_user


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
