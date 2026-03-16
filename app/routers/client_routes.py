# app/routers/client_routes.py

from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, Dict
from app.middleware.auth import get_current_user
from app.controllers.client_controller import ClientController
from app.models.client import ClientCreate, ClientUpdate
from app.services.lead_finder import lead_finder
from app.services.credits_service import CreditsService
from bson import ObjectId
from pydantic import BaseModel


router = APIRouter(prefix="/clients", tags=["clients"])


class LeadSearchRequest(BaseModel):
    city: str
    category: str
    radius_km: float = 5
    no_website_only: bool = True
    limit: int = 50


# ─── Create Client ────────────────────────────────────────
@router.post("", response_model=Dict)
async def create_client(
    data: ClientCreate,
    current_user: str = Depends(get_current_user)
):
    return await ClientController.create_client(data, current_user)


# ─── List Clients ─────────────────────────────────────────
@router.get("", response_model=Dict)
async def list_clients(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    has_website: Optional[bool] = Query(None),
    source: Optional[str] = Query(None),
    current_user: str = Depends(get_current_user)
):
    return await ClientController.list_clients(
        skip, limit, category, status, has_website, source, current_user
    )


# ─── Text Search ──────────────────────────────────────────
@router.get("/search", response_model=Dict)
async def search_clients(
    q: str = Query(..., min_length=1),
    current_user: str = Depends(get_current_user)
):
    return await ClientController.search_clients(q, current_user)


# ─── Nearby Search ────────────────────────────────────────
@router.get("/nearby", response_model=Dict)
async def search_nearby(
    lat: float = Query(...),
    lng: float = Query(...),
    radius_km: float = Query(10, ge=1, le=500),
    category: Optional[str] = Query(None),
    current_user: str = Depends(get_current_user)
):
    return await ClientController.search_nearby(lat, lng, radius_km, category, current_user)


# ─── Get One Client ───────────────────────────────────────
@router.get("/{client_id}", response_model=Dict)
async def get_client(
    client_id: str,
    current_user: str = Depends(get_current_user)
):
    return await ClientController.get_client(client_id, current_user)


# ─── Update Client ────────────────────────────────────────
@router.put("/{client_id}", response_model=Dict)
async def update_client(
    client_id: str,
    data: ClientUpdate,
    current_user: str = Depends(get_current_user)
):
    return await ClientController.update_client(client_id, data, current_user)


# ─── Delete Client ────────────────────────────────────────
@router.delete("/{client_id}", response_model=Dict)
async def delete_client(
    client_id: str,
    current_user: str = Depends(get_current_user)
):
    return await ClientController.delete_client(client_id, current_user)


# ─── Find Leads ───────────────────────────────────────────
@router.post("/find-leads", response_model=Dict)
async def find_leads(
    data: LeadSearchRequest,
    current_user: str = Depends(get_current_user)
):
    from app.services.mongo import mongo

    # ✅ Check credits BEFORE searching (2 credits per lead)
    credits_needed = min(data.limit, 50) * 2
    user = await mongo.users.find_one({"_id": ObjectId(current_user)})
    if not user:
        raise HTTPException(404, "User not found")
    if user.get("credits", 0) < credits_needed:
        raise HTTPException(
            400,
            f"Insufficient credits. Need {credits_needed}, have {int(user.get('credits', 0))}"
        )

    saved = await lead_finder.find_and_save_leads(
        city=data.city,
        category=data.category,
        radius_km=data.radius_km,
        owner_id=current_user,
        mongo=mongo,
        limit=min(data.limit, 50)
    )

    # ✅ Deduct 2 credits per lead actually saved (not duplicates)
    actual_credits = len(saved) * 2
    if actual_credits > 0:
        success, message = await CreditsService.deduct_credits(
            user_id=current_user,
            amount=float(actual_credits)
        )
        if not success:
            raise HTTPException(400, message)

    return {
        "status": 200,
        "success": True,
        "message": f"Found and saved {len(saved)} new leads",
        "data": {
            "total": len(saved),
            "leads": saved,
            "credits_used": actual_credits
        }
    }
