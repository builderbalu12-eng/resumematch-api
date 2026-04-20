from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from app.dependencies import get_current_user
from app.services.mongo import mongo

router = APIRouter(tags=["freelancers"])


@router.get("/freelancers/search")
async def search_freelancers(
    skill:      str   = Query(..., description="Skill or work type"),
    location:   str   = Query("", description="Preferred location (empty = any)"),
    budget_max: float = Query(0,  description="Max hourly rate USD (0 = any)"),
    limit:      int   = Query(10, ge=1, le=50),
    current_user: str = Depends(get_current_user),
):
    query: dict = {"available_for_hire": True}

    if skill.strip():
        query["freelance_skills"] = {"$elemMatch": {"$regex": skill.strip(), "$options": "i"}}

    if budget_max > 0:
        query["$or"] = [
            {"hourly_rate": {"$lte": budget_max}},
            {"hourly_rate": None},
            {"hourly_rate": 0},
        ]

    freelancers = []
    async for u in mongo.users.find(query).limit(limit):
        if str(u["_id"]) == current_user:
            continue
        prefs = u.get("job_preferences") or u.get("jobPreferences") or {}
        loc = prefs.get("preferred_location") or prefs.get("preferredLocation") or ""
        freelancers.append({
            "user_id":          str(u["_id"]),
            "name":             f"{u.get('firstName', '')} {u.get('lastName', '')}".strip(),
            "freelance_bio":    u.get("freelance_bio"),
            "freelance_skills": u.get("freelance_skills", []),
            "hourly_rate":      u.get("hourly_rate"),
            "portfolio_url":    u.get("portfolio_url"),
            "linkedin_url":     u.get("linkedin_url"),
            "github_url":       u.get("github_url"),
            "location":         loc,
        })

    return {"freelancers": freelancers, "count": len(freelancers)}
