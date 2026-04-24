import hmac as hmac_module
import hashlib
import base64
import httpx
from fastapi import HTTPException
from app.config import settings

BACKEND_URL = "https://resumematch-api-production.up.railway.app"


def _base_url() -> str:
    # Use dedicated CASHFREE_ENV setting — never derive from ENVIRONMENT
    # (ENVIRONMENT=production in Railway doesn't mean Cashfree is in production)
    if settings.cashfree_env == "production":
        return "https://api.cashfree.com/pg"
    return "https://sandbox.cashfree.com/pg"


def _headers() -> dict:
    return {
        "x-api-version": "2025-01-01",
        "x-client-id": settings.cashfree_app_id,
        "x-client-secret": settings.cashfree_secret_key,
        "Content-Type": "application/json",
    }


async def create_order(
    order_id: str,
    amount: float,
    currency: str,
    customer_id: str,
    customer_email: str,
    tags: dict,
) -> dict:
    return_url = f"{settings.frontend_base_url}/payment/success?order_id={{order_id}}"

    body = {
        "order_id": order_id[:50],
        "order_amount": round(float(amount), 2),
        "order_currency": currency.upper(),
        "customer_details": {
            "customer_id": str(customer_id)[:50],
            "customer_email": customer_email,
            "customer_phone": "9999999999",
        },
        "order_meta": {
            "return_url": return_url,
            "notify_url": f"{BACKEND_URL}/api/payments/webhook",
        },
        "order_tags": {k: str(v) for k, v in tags.items()},
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{_base_url()}/orders", headers=_headers(), json=body)
        if resp.status_code != 200:
            raise HTTPException(502, f"Cashfree create_order failed ({resp.status_code}): {resp.text}")
        return resp.json()


async def get_order(order_id: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{_base_url()}/orders/{order_id}", headers=_headers())
        if resp.status_code != 200:
            raise HTTPException(502, f"Cashfree get_order failed ({resp.status_code}): {resp.text}")
        return resp.json()


def verify_webhook_signature(payload: bytes, signature: str, timestamp: str) -> bool:
    try:
        message = timestamp + payload.decode("utf-8")
        computed = base64.b64encode(
            hmac_module.new(
                settings.cashfree_secret_key.encode(),
                message.encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        return computed == signature
    except Exception as e:
        print(f"🔴 verify_webhook_signature error: {e}")
        return False
