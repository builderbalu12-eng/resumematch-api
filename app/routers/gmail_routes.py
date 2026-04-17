"""Gmail OAuth + email-send routes."""
from typing import Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.middleware.auth import get_current_user
from app.services.gmail_service import (
    get_gmail_auth_url,
    handle_gmail_callback,
    send_email_via_gmail,
    disconnect_gmail,
)
from app.config import settings
from app.services.mongo import mongo
from bson import ObjectId

# ── Router registered under /api/gmail ──────────────────────────────────────
router = APIRouter(prefix="/gmail", tags=["gmail"])

# ── Separate router for the OAuth callback (no /api prefix) ─────────────────
gmail_callback_router = APIRouter(tags=["gmail"])


class SendLeadsEmailRequest(BaseModel):
    lead_ids: List[str]
    subject: str
    body_template: str   # may contain {business_name}, {name}, {address}, {category}, {your_name}
    from_name: str = ""


@router.get("/url")
async def gmail_auth_url(current_user: str = Depends(get_current_user)):
    url = get_gmail_auth_url(current_user)
    return {"success": True, "auth_url": url}


@router.delete("/disconnect")
async def gmail_disconnect(current_user: str = Depends(get_current_user)):
    await disconnect_gmail(current_user)
    return {"success": True, "message": "Gmail disconnected"}


@gmail_callback_router.get("/auth/gmail/callback")
async def gmail_callback(code: str = Query(...), state: str = Query(...)):
    """OAuth callback — state = user_id (set during auth URL generation)."""
    try:
        result = await handle_gmail_callback(code, state)
        frontend = settings.frontend_uri or settings.frontend_base_url
        return RedirectResponse(url=f"{frontend}/profile?gmail=connected&email={result['gmail_email']}")
    except Exception as e:
        frontend = settings.frontend_uri or settings.frontend_base_url
        import urllib.parse
        return RedirectResponse(url=f"{frontend}/profile?gmail=error&reason={urllib.parse.quote(str(e))}")


@router.post("/send-leads")
async def send_leads_email(
    body: SendLeadsEmailRequest,
    current_user: str = Depends(get_current_user),
) -> Dict:
    """Send a personalized email to each selected lead using the user's Gmail."""
    if not body.lead_ids:
        raise HTTPException(400, "No lead IDs provided")

    # Fetch all requested leads owned by this user
    oids = []
    for lid in body.lead_ids:
        try:
            oids.append(ObjectId(lid))
        except Exception:
            pass

    cursor = mongo.clients.find({"_id": {"$in": oids}, "owner_id": current_user})
    leads = await cursor.to_list(length=len(oids))

    if not leads:
        raise HTTPException(404, "No matching leads found")

    # Fetch user's name for {your_name} variable
    user_doc = await mongo.users.find_one({"_id": ObjectId(current_user)})
    your_name = f"{user_doc.get('firstName', '')} {user_doc.get('lastName', '')}".strip() if user_doc else ""

    sent, failed = 0, 0
    for lead in leads:
        email_addr = lead.get("email")
        if not email_addr:
            failed += 1
            continue

        # Personalize the template
        personalized = body.body_template
        replacements = {
            "{business_name}": lead.get("name", ""),
            "{name}":          lead.get("name", ""),
            "{address}":       lead.get("address", ""),
            "{category}":      lead.get("category", ""),
            "{your_name}":     your_name,
        }
        for var, val in replacements.items():
            personalized = personalized.replace(var, val)

        subject = body.subject
        for var, val in replacements.items():
            subject = subject.replace(var, val)

        try:
            await send_email_via_gmail(
                user_id=current_user,
                to_email=email_addr,
                subject=subject,
                body_html=personalized,
                from_name=body.from_name or your_name,
            )
            sent += 1
        except Exception:
            failed += 1

    return {
        "success": True,
        "sent": sent,
        "failed": failed,
        "message": f"Sent {sent} emails, {failed} failed (no email address or send error)",
    }
