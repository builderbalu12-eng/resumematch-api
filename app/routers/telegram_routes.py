from fastapi import APIRouter, Depends, Request
from typing import Any
from fastapi.responses import Response

from app.controllers.telegram_controller import telegram_controller
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/telegram", tags=["Telegram"])


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


# ─────────────────────────────────────────────────────────────
# GET /api/telegram/link
# Returns deep link + QR code image for frontend to display
# ─────────────────────────────────────────────────────────────
@router.get(
    "/link",
    summary="Get Telegram deep link and QR code to connect account",
)
async def get_link_url(
    current_user: Any = Depends(get_current_user),
):
    user_id = _extract_user_id(current_user)
    result  = await telegram_controller.get_link_url(user_id)

    # Strip raw bytes from JSON response — served via /qr endpoint
    result.pop("qr_bytes", None)
    return result


# ─────────────────────────────────────────────────────────────
# GET /api/telegram/qr
# Returns QR code as PNG image (img src in frontend)
# ─────────────────────────────────────────────────────────────
@router.get(
    "/qr",
    summary="Get QR code PNG image for Telegram linking",
    response_class=Response,
)
async def get_qr_code(
    current_user: Any = Depends(get_current_user),
):
    user_id = _extract_user_id(current_user)
    result  = await telegram_controller.get_link_url(user_id)

    qr_bytes = result.get("qr_bytes")
    if not qr_bytes:
        return Response(content="Already linked", status_code=200)

    return Response(
        content      = qr_bytes,
        media_type   = "image/png",
    )


# ─────────────────────────────────────────────────────────────
# GET /api/telegram/status
# Check if current user has linked Telegram
# ─────────────────────────────────────────────────────────────
@router.get(
    "/status",
    summary="Check if Telegram is connected to current account",
)
async def get_status(
    current_user: Any = Depends(get_current_user),
):
    user_id = _extract_user_id(current_user)
    return await telegram_controller.get_status(user_id)


# ─────────────────────────────────────────────────────────────
# DELETE /api/telegram/unlink
# Disconnect Telegram from account
# ─────────────────────────────────────────────────────────────
@router.delete(
    "/unlink",
    summary="Disconnect Telegram from current account",
)
async def unlink_telegram(
    current_user: Any = Depends(get_current_user),
):
    user_id = _extract_user_id(current_user)
    return await telegram_controller.unlink(user_id)


# ─────────────────────────────────────────────────────────────
# POST /api/telegram/webhook
# Telegram sends all bot messages here (no auth needed)
# ─────────────────────────────────────────────────────────────
@router.post(
    "/webhook",
    summary="Telegram webhook — receives all bot messages",
    include_in_schema=False,   # hide from Swagger docs
)
async def telegram_webhook(request: Request):
    data = await request.json()
    return await telegram_controller.handle_webhook(data)
