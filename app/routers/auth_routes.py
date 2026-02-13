from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse
from app.models.user import UserCreate, LoginRequest
from app.controllers.auth_controller import AuthController, AuthResponse
from app.controllers.google_auth_controller import GoogleAuthController

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse)
async def register(user: UserCreate):
    return await AuthController.register(user)


@router.post("/login", response_model=AuthResponse)
async def login(login_data: LoginRequest):
    # Pass the entire model (not separate args)
    return await AuthController.login(login_data)


@router.get("/google/url")
async def google_auth_url():
    auth_url = await GoogleAuthController.get_google_auth_url()  # ← add await here
    return {"success": True, "auth_url": auth_url}


# Separate router for Google callback (NO /api prefix)
google_callback_router = APIRouter(tags=["auth"])

@google_callback_router.get("/auth/google/callback")  # ← FIXED: add /auth/ here
async def google_callback(code: str = Query(...)):
    print("Google callback HIT with code:", code[:20] + "...")
    try:
        return await GoogleAuthController.google_callback(code)
    except Exception as e:
        print("Google callback ERROR:", str(e))
        return {"error": str(e)}