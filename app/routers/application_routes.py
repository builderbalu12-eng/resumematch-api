import json
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime, timezone, timedelta

from app.middleware.auth import get_current_user
from app.models.application import ApplicationRecordCreate, ApplicationRecordUpdate
from app.services.mongo import mongo
from app.services.credits_service import CreditsService

router = APIRouter(tags=["applications"])


@router.post("/applications", response_model=dict)
async def create_application(
    record: ApplicationRecordCreate,
    current_user: str = Depends(get_current_user),
):
    doc = {**record.dict(), "userId": current_user, "createdAt": datetime.utcnow()}
    result = await mongo.applications.insert_one(doc)
    return {"id": str(result.inserted_id), "message": "saved"}


@router.get("/applications", response_model=dict)
async def list_applications(
    current_user: str = Depends(get_current_user),
):
    cursor = mongo.applications.find({"userId": current_user}).sort("createdAt", -1).limit(100)
    docs = await cursor.to_list(100)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"applications": docs}


PIPELINE_STAGES_ORDER = [
    "evaluated", "applied", "responded", "contacted",
    "interview", "offer", "rejected", "discarded",
]


@router.get("/applications/stats", response_model=dict)
async def get_application_stats(
    current_user: str = Depends(get_current_user),
):
    pipeline = [
        {"$match": {"userId": current_user}},
        {
            "$group": {
                "_id": "$pipelineStage",
                "count": {"$sum": 1},
                # $avg returns null automatically when there are no docs,
                # but we need it to be null (None) for stages with 0 apps.
                # matchPercentage of 0 should not skew the average, so only
                # average docs where matchPercentage > 0.
                "sum_ats": {"$sum": "$matchPercentage"},
                "count_with_ats": {
                    "$sum": {
                        "$cond": [{"$gt": ["$matchPercentage", 0]}, 1, 0]
                    }
                },
                "sum_ats_nonzero": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$matchPercentage", 0]},
                            "$matchPercentage",
                            0,
                        ]
                    }
                },
            }
        },
    ]
    raw = await mongo.applications.aggregate(pipeline).to_list(None)

    # Build lookup by stage name
    by_stage: dict = {}
    for r in raw:
        stage = r["_id"] or "evaluated"
        count_with_ats = r.get("count_with_ats", 0)
        avg_ats = (
            round(r["sum_ats_nonzero"] / count_with_ats, 1)
            if count_with_ats > 0
            else None
        )
        by_stage[stage] = {"count": r["count"], "avg_ats": avg_ats}

    total = sum(v["count"] for v in by_stage.values())

    stage_breakdown = {s: by_stage.get(s, {}).get("count", 0) for s in PIPELINE_STAGES_ORDER}
    avg_ats_by_stage = {s: by_stage.get(s, {}).get("avg_ats", None) for s in PIPELINE_STAGES_ORDER}

    return {
        "totalApplications": total,
        "stageBreakdown": stage_breakdown,
        "avgAtsScoreByStage": avg_ats_by_stage,
    }


@router.get("/applications/insights", response_model=dict)
async def get_application_insights(
    current_user: str = Depends(get_current_user),
):
    # ── Cache check (7-day TTL) ───────────────────────────
    cached = await mongo.db["application_insights"].find_one({"userId": current_user})
    if cached:
        generated_at: datetime = cached.get("generatedAt", datetime.utcnow())
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - generated_at
        if age < timedelta(days=7):
            return {
                "observations": cached.get("observations", []),
                "generatedAt": generated_at.isoformat(),
                "cached": True,
            }

    # ── Fetch all applications ────────────────────────────
    apps = await mongo.applications.find({"userId": current_user}).to_list(500)
    total = len(apps)
    if total == 0:
        raise HTTPException(status_code=400, detail="No applications to analyze")

    # ── Compute aggregated stats ──────────────────────────
    stage_counts: dict = {}
    ats_by_stage: dict = {}
    ats_count_by_stage: dict = {}

    for app in apps:
        stage = app.get("pipelineStage", "evaluated")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        score = app.get("matchPercentage", 0)
        if score > 0:
            ats_by_stage[stage] = ats_by_stage.get(stage, 0) + score
            ats_count_by_stage[stage] = ats_count_by_stage.get(stage, 0) + 1

    avg_ats: dict = {}
    for stage, total_score in ats_by_stage.items():
        count = ats_count_by_stage.get(stage, 0)
        avg_ats[stage] = round(total_score / count, 1) if count > 0 else None

    # Response rate: % of "applied" that reached responded/contacted/interview/offer
    applied = stage_counts.get("applied", 0)
    progressed = sum(
        stage_counts.get(s, 0)
        for s in ("responded", "contacted", "interview", "offer")
    )
    response_rate = round(progressed / applied * 100, 1) if applied > 0 else 0

    # Interview conversion: % that reached interview/offer out of all non-rejected
    interview_plus = stage_counts.get("interview", 0) + stage_counts.get("offer", 0)
    interview_rate = round(interview_plus / total * 100, 1) if total > 0 else 0

    stats_payload = {
        "total_applications": total,
        "stage_breakdown": stage_counts,
        "avg_ats_by_stage": avg_ats,
        "response_rate_pct": response_rate,
        "interview_conversion_pct": interview_rate,
    }

    # ── Credit deduction ──────────────────────────────────
    cost = await CreditsService.get_feature_cost("application_insights")
    if cost <= 0:
        cost = 1.0
    ok, msg = await CreditsService.deduct_credits(current_user, cost, "application_insights")
    if not ok:
        raise HTTPException(status_code=402, detail=msg)

    # ── AI call ───────────────────────────────────────────
    prompt = f"""You are a job search strategist. Analyze these job application statistics and provide 3–5 actionable observations.

Application Stats:
{json.dumps(stats_payload, indent=2)}

Write 3–5 bullet points like:
- "You get 3x more responses when your ATS score is above 75"
- "Series B companies are responding at 2x the rate of enterprises for your profile"
- "Applications to roles with 'LLM' in the title convert better for you"

Be specific and data-driven. Use the actual numbers. Return ONLY a JSON array:
["observation 1", "observation 2", "observation 3"]"""

    from app.services.ai_provider_service import call_ai
    result = call_ai(prompt, temperature=0.4, max_tokens=600)

    if "error" in result:
        await CreditsService.refund_credits(current_user, cost, "Insights AI call failed")
        raise HTTPException(status_code=500, detail=result["error"])

    # call_ai returns a dict; the prompt asks for a JSON array which will be
    # parsed as a list at the top level.  Handle both cases.
    observations: list = []
    if isinstance(result, list):
        observations = result
    elif isinstance(result, dict):
        # Sometimes the AI wraps it: {"observations": [...]} or {"0": "...", ...}
        for key in ("observations", "items", "results"):
            if key in result and isinstance(result[key], list):
                observations = result[key]
                break
        if not observations:
            # Fallback: collect all string values
            observations = [v for v in result.values() if isinstance(v, str)]

    if not observations:
        await CreditsService.refund_credits(current_user, cost, "Insights returned empty observations")
        raise HTTPException(status_code=500, detail="AI returned no observations. Please try again.")

    observations = [str(o) for o in observations[:5]]  # cap at 5

    # ── Persist to cache ──────────────────────────────────
    now = datetime.utcnow()
    await mongo.db["application_insights"].update_one(
        {"userId": current_user},
        {"$set": {"observations": observations, "generatedAt": now}},
        upsert=True,
    )

    return {
        "observations": observations,
        "generatedAt": now.isoformat(),
        "cached": False,
    }


@router.patch("/applications/{app_id}", response_model=dict)
async def update_application(
    app_id: str,
    update: ApplicationRecordUpdate,
    current_user: str = Depends(get_current_user),
):
    try:
        oid = ObjectId(app_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid application ID")

    fields = update.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = await mongo.applications.update_one(
        {"_id": oid, "userId": current_user},
        {"$set": fields},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Application not found")

    return {"message": "updated"}


def _compute_urgency(days: int) -> str:
    if days > 14:
        return "URGENT"
    if days > 7:
        return "OVERDUE"
    if days > 3:
        return "WAITING"
    return "NOT_YET"


@router.post("/applications/{app_id}/followup", response_model=dict)
async def generate_followup(
    app_id: str,
    current_user: str = Depends(get_current_user),
):
    try:
        oid = ObjectId(app_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid application ID")

    app_doc = await mongo.applications.find_one({"_id": oid, "userId": current_user})
    if not app_doc:
        raise HTTPException(status_code=404, detail="Application not found")

    # ── Compute timing ────────────────────────────────────
    created_at = app_doc.get("createdAt", datetime.utcnow())
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days_since_applied = (now - created_at).days
    urgency = _compute_urgency(days_since_applied)

    role = app_doc.get("jobTitle", "the role")
    company = app_doc.get("company", "the company")

    # ── Credit deduction ──────────────────────────────────
    cost = await CreditsService.get_feature_cost("job_followup")
    if cost <= 0:
        cost = 1.0
    ok, msg = await CreditsService.deduct_credits(current_user, cost, "job_followup")
    if not ok:
        raise HTTPException(status_code=402, detail=msg)

    # ── AI call ───────────────────────────────────────────
    prompt = f"""Write two professional follow-up drafts for a job application.

Job: {role} at {company}
Days since applied: {days_since_applied}

Return ONLY valid JSON:
{{
  "emailDraft": "A professional follow-up email. Max 120 words. Start with 'Subject: Following up — {role} Application'. Be specific to the company and role. Mention days elapsed naturally.",
  "linkedinDraft": "A LinkedIn message. MAX 300 characters absolute limit. Warm, professional, specific to company/role. No hashtags."
}}"""

    from app.services.ai_provider_service import call_ai
    result = call_ai(prompt, temperature=0.4, max_tokens=600)

    if "error" in result:
        await CreditsService.refund_credits(current_user, cost, "Follow-up generation AI call failed")
        raise HTTPException(status_code=500, detail=result["error"])

    email_draft = result.get("emailDraft", "")
    linkedin_draft = result.get("linkedinDraft", "")

    if not email_draft or not linkedin_draft:
        await CreditsService.refund_credits(current_user, cost, "Follow-up generation returned incomplete response")
        raise HTTPException(status_code=500, detail="AI returned an incomplete response. Please try again.")

    # Enforce LinkedIn 300-char hard limit
    linkedin_draft = linkedin_draft[:300]

    return {
        "emailDraft": email_draft,
        "linkedinDraft": linkedin_draft,
        "daysSinceApplied": days_since_applied,
        "urgency": urgency,
    }


@router.delete("/applications/{app_id}", response_model=dict)
async def delete_application(
    app_id: str,
    current_user: str = Depends(get_current_user),
):
    try:
        oid = ObjectId(app_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid application ID")
    await mongo.applications.delete_one({"_id": oid, "userId": current_user})
    return {"message": "deleted"}
