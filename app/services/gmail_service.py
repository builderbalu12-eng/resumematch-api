"""Gmail OAuth + send service.

Uses the Gmail REST API (messages.send) with per-user OAuth tokens.
Scope required: https://www.googleapis.com/auth/gmail.send
"""
import base64
import email as email_lib
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import httpx
from bson import ObjectId
from fastapi import HTTPException

from app.config import settings
from app.services.mongo import mongo


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def get_gmail_auth_url(user_id: str) -> str:
    """Build OAuth URL that requests gmail.send scope. state = user_id."""
    redirect_uri = settings.gmail_redirect_uri or f"{(settings.frontend_uri or settings.frontend_base_url).rstrip('/')}/auth/gmail/callback"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "scope": GMAIL_SEND_SCOPE,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "state": user_id,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


async def handle_gmail_callback(code: str, user_id: str) -> dict:
    """Exchange code for tokens and persist in user doc."""
    redirect_uri = settings.gmail_redirect_uri or f"{(settings.frontend_uri or settings.frontend_base_url).rstrip('/')}/auth/gmail/callback"
    payload = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(TOKEN_URL, data=payload)
        if resp.status_code != 200:
            raise HTTPException(400, f"Gmail token exchange failed: {resp.text}")
        tokens = resp.json()

    # Fetch the Gmail address from userinfo
    userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
    async with httpx.AsyncClient() as client:
        ui = await client.get(userinfo_url, headers={"Authorization": f"Bearer {tokens['access_token']}"})
        gmail_email = ui.json().get("email", "") if ui.status_code == 200 else ""

    await mongo.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {
            "gmail_access_token": tokens.get("access_token"),
            "gmail_refresh_token": tokens.get("refresh_token"),
            "gmail_email": gmail_email,
            "gmail_connected": True,
        }}
    )
    return {"gmail_email": gmail_email}


async def _refresh_access_token(user_id: str, refresh_token: str) -> str:
    """Refresh Gmail access token and persist the new one."""
    payload = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(TOKEN_URL, data=payload)
        if resp.status_code != 200:
            raise HTTPException(400, "Gmail token refresh failed. Please reconnect Gmail.")
        new_token = resp.json()["access_token"]

    await mongo.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"gmail_access_token": new_token}}
    )
    return new_token


async def send_email_via_gmail(
    user_id: str,
    to_email: str,
    subject: str,
    body_html: str,
    from_name: Optional[str] = None,
) -> None:
    """Send one email via the user's connected Gmail account."""
    user = await mongo.users.find_one({"_id": ObjectId(user_id)})
    if not user or not user.get("gmail_connected"):
        raise HTTPException(400, "Gmail not connected. Please connect Gmail in Settings.")

    access_token = user["gmail_access_token"]
    refresh_token = user.get("gmail_refresh_token")
    sender_email = user.get("gmail_email", "")
    sender = f"{from_name} <{sender_email}>" if from_name else sender_email

    msg = MIMEMultipart("alternative")
    msg["To"] = to_email
    msg["From"] = sender
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    async def _send(token: str) -> httpx.Response:
        async with httpx.AsyncClient() as client:
            return await client.post(
                SEND_URL,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"raw": raw},
            )

    resp = await _send(access_token)
    if resp.status_code == 401 and refresh_token:
        # Token expired — refresh and retry once
        access_token = await _refresh_access_token(user_id, refresh_token)
        resp = await _send(access_token)

    if resp.status_code not in (200, 204):
        raise HTTPException(500, f"Gmail send failed: {resp.text}")


async def disconnect_gmail(user_id: str) -> None:
    await mongo.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {
            "gmail_access_token": None,
            "gmail_refresh_token": None,
            "gmail_email": None,
            "gmail_connected": False,
        }}
    )
