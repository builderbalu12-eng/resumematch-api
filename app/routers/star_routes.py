import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import List, Optional
from datetime import datetime
from bson import ObjectId

from app.middleware.auth import get_current_user
from app.services.mongo import mongo
from app.services.credits_service import CreditsService

router = APIRouter(tags=["STAR Stories"])


# ── Pydantic models ────────────────────────────────────────

class StarStoryCreate(BaseModel):
    title: str
    situation: str
    task: str
    action: str
    result: str
    tags: List[str] = []

    @field_validator("title", "situation", "task", "action", "result")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be empty")
        return v.strip()

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: List[str]) -> List[str]:
        return [t.strip() for t in v if t.strip()]


class StarStoryUpdate(BaseModel):
    title: Optional[str] = None
    situation: Optional[str] = None
    task: Optional[str] = None
    action: Optional[str] = None
    result: Optional[str] = None
    tags: Optional[List[str]] = None

    @field_validator("title", "situation", "task", "action", "result", mode="before")
    @classmethod
    def must_not_be_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not str(v).strip():
            raise ValueError("Field must not be empty")
        return v.strip() if v is not None else v

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        return [t.strip() for t in v if t.strip()]


class SuggestRequest(BaseModel):
    jobTitle: str
    company: str
    jobDescription: str


# ── Serialiser ─────────────────────────────────────────────

def _serialize(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    if "createdAt" in doc and isinstance(doc["createdAt"], datetime):
        doc["createdAt"] = doc["createdAt"].isoformat()
    if "updatedAt" in doc and isinstance(doc["updatedAt"], datetime):
        doc["updatedAt"] = doc["updatedAt"].isoformat()
    return doc


# ── GET /api/star-stories ──────────────────────────────────

@router.get("/star-stories", response_model=dict)
async def list_stories(current_user: str = Depends(get_current_user)):
    cursor = mongo.star_stories.find({"userId": current_user}).sort("createdAt", -1)
    docs = await cursor.to_list(500)
    return {"stories": [_serialize(d) for d in docs]}


# ── POST /api/star-stories ─────────────────────────────────

@router.post("/star-stories", response_model=dict)
async def create_story(
    body: StarStoryCreate,
    current_user: str = Depends(get_current_user),
):
    now = datetime.utcnow()
    doc = {
        **body.model_dump(),
        "userId": current_user,
        "createdAt": now,
        "updatedAt": now,
    }
    result = await mongo.star_stories.insert_one(doc)
    doc["_id"] = result.inserted_id
    return {"story": _serialize(doc)}


# ── PATCH /api/star-stories/{story_id} ────────────────────

@router.patch("/star-stories/{story_id}", response_model=dict)
async def update_story(
    story_id: str,
    body: StarStoryUpdate,
    current_user: str = Depends(get_current_user),
):
    try:
        oid = ObjectId(story_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid story ID")

    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    fields["updatedAt"] = datetime.utcnow()

    result = await mongo.star_stories.find_one_and_update(
        {"_id": oid, "userId": current_user},
        {"$set": fields},
        return_document=True,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Story not found")

    return {"story": _serialize(result)}


# ── DELETE /api/star-stories/{story_id} ───────────────────

@router.delete("/star-stories/{story_id}", response_model=dict)
async def delete_story(
    story_id: str,
    current_user: str = Depends(get_current_user),
):
    try:
        oid = ObjectId(story_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid story ID")

    result = await mongo.star_stories.delete_one({"_id": oid, "userId": current_user})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Story not found")

    return {"success": True}


# ── POST /api/star-stories/suggest ────────────────────────

@router.post("/star-stories/suggest", response_model=dict)
async def suggest_stories(
    body: SuggestRequest,
    current_user: str = Depends(get_current_user),
):
    # Fetch user's stories
    cursor = mongo.star_stories.find({"userId": current_user}).sort("createdAt", -1)
    stories = await cursor.to_list(500)

    if not stories:
        return {"suggestions": [], "message": "Add stories to your bank first"}

    # Credit deduction
    cost = await CreditsService.get_feature_cost("star_suggest")
    if cost <= 0:
        cost = 1.0
    ok, msg = await CreditsService.deduct_credits(current_user, cost, "star_suggest")
    if not ok:
        raise HTTPException(status_code=402, detail=msg)

    # Build stories payload for prompt (id + STAR fields only)
    stories_for_prompt = [
        {
            "id": str(s["_id"]),
            "title": s.get("title", ""),
            "situation": s.get("situation", ""),
            "task": s.get("task", ""),
            "action": s.get("action", ""),
            "result": s.get("result", ""),
            "tags": s.get("tags", []),
        }
        for s in stories
    ]

    prompt = f"""You are an interview coach. Given these behavioral stories and a job description, rank the top 3 most relevant stories.

Job: {body.jobTitle} at {body.company}
Job Description: {body.jobDescription[:2000]}

Candidate's STAR Stories:
{json.dumps(stories_for_prompt, indent=2)}

Return ONLY valid JSON:
{{
  "suggestions": [
    {{
      "storyId": "...",
      "title": "...",
      "reason": "One sentence on why this story fits this specific role."
    }}
  ]
}}
Return the top 3 most relevant stories only."""

    from app.services.ai_provider_service import call_ai
    ai_result = call_ai(prompt, temperature=0.3, max_tokens=600)

    if "error" in ai_result:
        await CreditsService.refund_credits(current_user, cost, "STAR suggest AI call failed")
        raise HTTPException(status_code=500, detail=ai_result["error"])

    suggestions = ai_result.get("suggestions", [])
    if not isinstance(suggestions, list):
        await CreditsService.refund_credits(current_user, cost, "STAR suggest returned malformed response")
        raise HTTPException(status_code=500, detail="AI returned an unexpected format. Please try again.")

    # Cap at 3
    suggestions = suggestions[:3]

    return {"suggestions": suggestions}
