# app/controllers/google_auth_controller.py - full file
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
import httpx
import urllib.parse
import json
import base64
from app.models.user import UserResponse
from app.controllers.auth_controller import AuthData, AuthResponse
from app.services.mongo import mongo
from app.config import settings
from datetime import datetime, timedelta
from jose import jwt

class GoogleAuthController:
    @staticmethod
    async def get_google_auth_url() -> str:
        base_url = "https://accounts.google.com/o/oauth2/v2/auth"
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "scope": "openid email profile",
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{base_url}?{urllib.parse.urlencode(params)}"

    @staticmethod
    async def exchange_code_for_token(code: str) -> dict:
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.google_redirect_uri,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            if response.status_code != 200:
                raise HTTPException(400, "Failed to exchange code for token")
            return response.json()

    @staticmethod
    async def get_google_user_info(access_token: str) -> dict:
        url = "https://www.googleapis.com/oauth2/v2/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                raise HTTPException(400, "Failed to get user info from Google")
            return response.json()

    @staticmethod
    def _prepare_user_data(user_doc: dict) -> dict:
        user_doc["uid"] = str(user_doc["_id"])
        del user_doc["_id"]
        if "auth_provider" not in user_doc:
            user_doc["auth_provider"] = "local"
        if "google_id" not in user_doc:
            user_doc["google_id"] = None
        return user_doc

    @staticmethod
    async def google_callback(code: str, frontend_url: str = settings.frontend_uri) -> RedirectResponse:
        print("=== Google Callback Started ===")
        print("Received code:", code if code else "No code!")
        # print("Full query params:", dict(request.query_params))  # if you have Request injected

        try:
            print("Exchanging code for tokens...")
            token_data = await GoogleAuthController.exchange_code_for_token(code)
            print("Token exchange success:", token_data)

            access_token = token_data.get("access_token")
            if not access_token:
                raise HTTPException(400, "No access token received")

            print("Getting user info from Google...")
            user_info = await GoogleAuthController.get_google_user_info(access_token)
            print("Google user info:", user_info)

            collection = mongo.users

            print("Checking for existing user...")
            existing = await collection.find_one({
                "$or": [{"email": user_info["email"]}, {"google_id": user_info["id"]}]
            })

            if existing:
                print("Updating existing user:", existing["email"])
                await collection.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"google_id": user_info["id"], "auth_provider": "google"}}
                )
                user = existing
            else:
                print("Creating new Google user:", user_info["email"])
                new_user = {
                    "firstName": user_info.get("given_name", ""),
                    "lastName": user_info.get("family_name", ""),
                    "email": user_info["email"],
                    "password": None,
                    "credits": 150.0,
                    "created_at": datetime.utcnow(),
                    "auth_provider": "google",
                    "google_id": user_info["id"]
                }
                result = await collection.insert_one(new_user)
                user = {**new_user, "_id": result.inserted_id}

            user_dict = dict(user)
            user_dict["_id"] = str(user["_id"])

            print("Generating JWT...")
            token = jwt.encode(
                {"sub": user_dict["_id"], "email": user_dict["email"], "exp": datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)},
                settings.jwt_secret,
                algorithm=settings.jwt_algorithm
            )

            auth_data = {
                "user": UserResponse(**user_dict).dict(),
                "access_token": token,
                "token_type": "bearer"
            }

            print("Encoding auth_data to base64...")
            auth_json = json.dumps(auth_data, default=str)
            auth_b64 = base64.urlsafe_b64encode(auth_json.encode()).decode()

            redirect_url = f"{frontend_url}/auth/callback?auth_data={auth_b64}&success=true"
            print("Redirecting to:", redirect_url)
            return RedirectResponse(url=redirect_url)

        except Exception as e:
            print("Google callback FAILED:", str(e))
            print("Full error:", traceback.format_exc())
            error_url = f"{frontend_url}/auth/callback?error={urllib.parse.quote(str(e))}&success=false"
            return RedirectResponse(url=error_url)