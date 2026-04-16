from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from bson import ObjectId

from app.middleware.auth import get_current_user
from app.services.mongo import mongo
from app.services.credits_service import CreditsService

router = APIRouter(tags=["Job Evaluation"])


def _uid(current_user) -> str:
    if isinstance(current_user, str):
        return current_user
    if isinstance(current_user, dict):
        return str(
            current_user.get("_id") or current_user.get("id") or current_user.get("user_id") or ""
        )
    return str(current_user)


# ── Request / Response models ──────────────────────────────

class EvaluateJobRequest(BaseModel):
    jobUrl: str
    jobTitle: str
    company: str
    description: str
    userResumeId: Optional[str] = None


class EvaluationAxis(BaseModel):
    name: str
    grade: str
    score: float
    reasoning: str


class JobEvaluationResult(BaseModel):
    overallGrade: str
    overallScore: float
    verdict: str
    axes: List[EvaluationAxis]
    cached: bool = False


# ── Helper: fetch resume text ─────────────────────────────

async def _get_resume_text(user_id: str, resume_id: Optional[str] = None) -> str:
    query = {"user_id": user_id}
    if resume_id:
        try:
            query["_id"] = ObjectId(resume_id)
        except Exception:
            pass

    doc = await mongo.incoming_resumes.find_one(query, sort=[("created_at", -1)])
    if not doc:
        return ""

    extracted = doc.get("extracted_data")
    if extracted and isinstance(extracted, dict):
        parts = []
        for key, val in extracted.items():
            if val:
                if isinstance(val, list):
                    parts.append(f"{key}: {', '.join(str(v) for v in val)}")
                else:
                    parts.append(f"{key}: {val}")
        return "\n".join(parts)

    return doc.get("raw_text", "") or ""


# ── POST /api/jobs/evaluate ───────────────────────────────

@router.post("/jobs/evaluate", response_model=dict)
async def evaluate_job(
    payload: EvaluateJobRequest,
    current_user=Depends(get_current_user),
):
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Check cache first
    cached_doc = await mongo.job_evaluations.find_one({
        "userId": user_id,
        "jobUrl": payload.jobUrl,
    })
    if cached_doc:
        cached_doc.pop("_id", None)
        cached_doc["cached"] = True
        return {"data": cached_doc}

    # Check credits
    cost = await CreditsService.get_feature_cost("job_evaluate")
    if cost > 0:
        ok, msg = await CreditsService.deduct_credits(user_id, cost, "job_evaluate")
        if not ok:
            raise HTTPException(status_code=402, detail=msg)

    # Fetch resume + north star
    resume_text = await _get_resume_text(user_id, payload.userResumeId)
    user_doc = await mongo.users.find_one({"_id": ObjectId(user_id)})
    north_star = (user_doc or {}).get("northStar", "") or ""

    # Build AI prompt
    resume_section = f"\n\nCANDIDATE RESUME:\n{resume_text}" if resume_text else ""
    north_star_section = f"\n\nCANDIDATE CAREER GOALS (North Star):\n{north_star}" if north_star else ""

    prompt = f"""You are evaluating a job posting for a candidate. Score the job on exactly 6 axes and return ONLY valid JSON.

JOB TITLE: {payload.jobTitle}
COMPANY: {payload.company}
JOB DESCRIPTION:
{payload.description[:3000]}{resume_section}{north_star_section}

Evaluate the job on these 6 axes:
1. cv_match — How well does the candidate's resume match the JD requirements?
2. north_star — Does this role advance the candidate's stated career goals? (if no goals given, score 3.0)
3. compensation — Is the compensation competitive for this role/location/level based on market knowledge?
4. cultural_signals — What does the JD language signal about company culture?
5. red_flags — Are there stressful signals (urgent hire, vague role, over-leveled YOE requirements)?
6. posting_legitimacy — Is this a real, active, recently posted job? Check for signs of ghost jobs.

Return ONLY this JSON (no markdown, no explanation):
{{
  "overallGrade": "B+",
  "overallScore": 3.8,
  "verdict": "Worth applying — strong CV match with minor concerns",
  "axes": [
    {{"name": "CV Match", "key": "cv_match", "grade": "A", "score": 4.5, "reasoning": "one sentence"}},
    {{"name": "North Star", "key": "north_star", "grade": "B", "score": 3.5, "reasoning": "one sentence"}},
    {{"name": "Compensation", "key": "compensation", "grade": "C+", "score": 2.8, "reasoning": "one sentence"}},
    {{"name": "Cultural Signals", "key": "cultural_signals", "grade": "B+", "score": 3.7, "reasoning": "one sentence"}},
    {{"name": "Red Flags", "key": "red_flags", "grade": "A-", "score": 4.2, "reasoning": "one sentence"}},
    {{"name": "Posting Legitimacy", "key": "posting_legitimacy", "grade": "B", "score": 3.5, "reasoning": "one sentence"}}
  ]
}}"""

    from app.services.ai_provider_service import call_ai
    result = call_ai(prompt, temperature=0.2, max_tokens=1024)

    if "error" in result:
        if cost > 0:
            await CreditsService.refund_credits(user_id, cost, "Job evaluation failed")
        raise HTTPException(status_code=500, detail=result["error"])

    # Cache the result
    doc = {
        "userId": user_id,
        "jobUrl": payload.jobUrl,
        "jobTitle": payload.jobTitle,
        "company": payload.company,
        "overallGrade": result.get("overallGrade", "C"),
        "overallScore": result.get("overallScore", 3.0),
        "verdict": result.get("verdict", ""),
        "axes": result.get("axes", []),
        "cached": False,
        "createdAt": datetime.utcnow(),
    }
    await mongo.job_evaluations.insert_one(doc)
    doc.pop("_id", None)

    return {"data": doc}
