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

    # ✅ Fetch cost dynamically from credits_on_features collection
    cost_per_lead  = await CreditsService.get_feature_cost("find_leads")
    credits_needed = min(data.limit, 50) * cost_per_lead

    user = await mongo.users.find_one({"_id": ObjectId(current_user)})
    if not user:
        raise HTTPException(404, "User not found")

    if user.get("credits", 0) < credits_needed:
        raise HTTPException(
            400,
            f"Insufficient credits. Need {int(credits_needed)}, have {int(user.get('credits', 0))}"
        )

    saved = await lead_finder.find_and_save_leads(
        city=data.city,
        category=data.category,
        radius_km=data.radius_km,
        owner_id=current_user,
        mongo=mongo,
        limit=min(data.limit, 50)
    )

    # ✅ Deduct only for actually saved leads (not duplicates)
    actual_credits = len(saved) * cost_per_lead
    if actual_credits > 0:
        success, message = await CreditsService.deduct_credits(
            user_id=current_user,
            amount=float(actual_credits)
        )
        if not success:
            raise HTTPException(400, message)

        # ✅ Log with feature details
        await CreditsService.log_deduction(
            user_id=current_user,
            amount=float(actual_credits),
            feature="find_leads",
            function_name="find_leads_api",
            description=f"Found {len(saved)} leads in {data.city} [{data.category}]"
        )

    return {
        "status": 200,
        "success": True,
        "message": f"Found and saved {len(saved)} new leads",
        "data": {
            "total":        len(saved),
            "leads":        saved,
            "credits_used": int(actual_credits)
        }
    }



# ─── AI Analyze Lead ──────────────────────────────────────
@router.post("/{client_id}/analyze", response_model=Dict)
async def analyze_lead(
    client_id: str,
    current_user: str = Depends(get_current_user)
):
    """Generate an AI outreach insight for a lead. Cached on lead doc."""
    from app.services.mongo import mongo
    from app.services.credits_service import CreditsService
    from app.services.ai_provider_service import call_ai_text_async

    lead = await mongo.clients.find_one({"_id": ObjectId(client_id), "owner_id": current_user})
    if not lead:
        raise HTTPException(404, "Lead not found")

    if lead.get("ai_insight"):
        return {"success": True, "insight": lead["ai_insight"], "cached": True}

    cost = await CreditsService.get_feature_cost("lead_analyze")
    success, msg = await CreditsService.deduct_credits(current_user, float(cost))
    if not success:
        raise HTTPException(400, msg)

    await CreditsService.log_deduction(
        user_id=current_user,
        amount=float(cost),
        feature="lead_analyze",
        function_name="analyze_lead",
        description=f"AI insight for lead: {lead.get('name', client_id)}"
    )

    prompt = (
        f"Analyze this local business for a freelancer or agency selling web design / digital marketing services.\n\n"
        f"Business: {lead.get('name', 'Unknown')}\n"
        f"Category: {lead.get('category', 'Unknown')}\n"
        f"Address: {lead.get('address', 'Unknown')}\n"
        f"Google Rating: {lead.get('rating', 'N/A')} ({lead.get('rating_count', 0)} reviews)\n"
        f"Has Website: {'Yes' if lead.get('has_website') else 'No'}\n\n"
        "Suggest the best outreach angle. What pain point should be highlighted? "
        "What service would most benefit them? Be specific and concise (3-4 sentences)."
    )

    insight = await call_ai_text_async(prompt)

    await mongo.clients.update_one(
        {"_id": ObjectId(client_id)},
        {"$set": {"ai_insight": insight}}
    )

    return {"success": True, "insight": insight, "cached": False}


# ─── Get Find Leads Credit Cost ───────────────────────────
@router.get("/credits/find-leads", response_model=Dict)
async def get_credits_on_find_leads(
    current_user: str = Depends(get_current_user)
):
    cost = await CreditsService.get_feature_cost("find_leads")
    return {
        "success":       True,
        "feature":       "find_leads",
        "cost_per_unit": int(cost),
        "unit":          "per lead"
    }
