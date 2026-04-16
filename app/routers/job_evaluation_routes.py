from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime, timezone
from bson import ObjectId

from app.middleware.auth import get_current_user
from app.services.mongo import mongo
from app.services.credits_service import CreditsService

router = APIRouter(tags=["Job Evaluation"])


# ── Utility ───────────────────────────────────────────────

def _uid(current_user: Any) -> str:
    if isinstance(current_user, str):
        return current_user
    if isinstance(current_user, dict):
        return str(
            current_user.get("_id")
            or current_user.get("id")
            or current_user.get("user_id")
            or ""
        )
    return str(current_user)


# ── Pydantic models ────────────────────────────────────────

class EvaluateJobRequest(BaseModel):
    jobUrl: str
    jobTitle: str
    company: str
    description: str
    userResumeId: Optional[str] = None
    # Optional job metadata for ghost-job signals
    datePosted: Optional[str] = None   # ISO date string or human-readable
    salary: Optional[str] = None


# ── Resume text helper ─────────────────────────────────────

async def _get_resume_text(user_id: str, resume_id: Optional[str] = None) -> str:
    query: dict = {"user_id": user_id}
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
                parts.append(
                    f"{key}: {', '.join(str(v) for v in val)}"
                    if isinstance(val, list)
                    else f"{key}: {val}"
                )
        return "\n".join(parts)

    return doc.get("raw_text", "") or ""


# ── Ghost-job signal computation ───────────────────────────

def _ghost_job_signals(
    description: str,
    date_posted: Optional[str],
    salary: Optional[str],
) -> dict:
    """
    Pre-compute observable signals before the AI call so Gemini can
    reason about Posting Legitimacy with concrete data rather than guessing.
    """
    signals: dict = {}

    # Days since posted
    days_since: Optional[int] = None
    if date_posted:
        try:
            # Try ISO format first
            posted_dt = datetime.fromisoformat(date_posted.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if posted_dt.tzinfo is None:
                posted_dt = posted_dt.replace(tzinfo=timezone.utc)
            days_since = (now - posted_dt).days
        except Exception:
            pass
    signals["days_since_posted"] = days_since  # None = unknown

    # Salary presence
    signals["salary_listed"] = bool(salary and salary.strip())

    # Description length
    desc_len = len(description.strip())
    signals["description_length_chars"] = desc_len
    signals["description_thin"] = desc_len < 300  # suspiciously short JD

    return signals


def _signals_to_text(signals: dict) -> str:
    lines = []
    dsp = signals.get("days_since_posted")
    if dsp is not None:
        lines.append(f"- Days since posted: {dsp}")
        if dsp > 60:
            lines.append("  (WARNING: posted over 60 days ago — possible ghost job)")
        elif dsp > 30:
            lines.append("  (CAUTION: posted over 30 days ago)")
    else:
        lines.append("- Days since posted: unknown")

    lines.append(f"- Salary listed: {'Yes' if signals['salary_listed'] else 'No'}")
    lines.append(f"- Job description length: {signals['description_length_chars']} characters"
                 + (" (very thin — suspicious)" if signals["description_thin"] else ""))
    return "\n".join(lines)


# ── POST /api/jobs/evaluate ────────────────────────────────

@router.post("/jobs/evaluate", response_model=dict)
async def evaluate_job(
    payload: EvaluateJobRequest,
    current_user: Any = Depends(get_current_user),
):
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # ── 1. Cache check — no credits deducted on hit ────────
    cached_doc = await mongo.job_evaluations.find_one({
        "userId": user_id,
        "jobUrl": payload.jobUrl,
    })
    if cached_doc:
        result = cached_doc.get("evaluationResult", {})
        result["cached"] = True
        return {"data": result}

    # ── 2. Credit deduction — before any AI call ──────────
    cost = await CreditsService.get_feature_cost("job_evaluate")
    if cost <= 0:
        cost = 1.0   # safe default
    ok, msg = await CreditsService.deduct_credits(user_id, cost, "job_evaluate")
    if not ok:
        raise HTTPException(status_code=402, detail=msg)

    # ── 3. Fetch resume + north star ───────────────────────
    resume_text = await _get_resume_text(user_id, payload.userResumeId)
    user_doc = await mongo.users.find_one({"_id": ObjectId(user_id)})
    north_star = ((user_doc or {}).get("northStar") or "").strip()

    # ── 4. Compute ghost-job signals ───────────────────────
    signals = _ghost_job_signals(
        description=payload.description,
        date_posted=payload.datePosted,
        salary=payload.salary,
    )
    signals_text = _signals_to_text(signals)

    # ── 5. Build prompt ────────────────────────────────────
    resume_block = (
        f"\nCandidate's Resume:\n{resume_text[:4000]}\n"
        if resume_text
        else "\nCandidate's Resume: Not provided.\n"
    )
    north_star_block = (
        f"\nCandidate's Career Goals (North Star):\n{north_star}\n"
        if north_star
        else "\nCandidate's Career Goals (North Star): Not provided — score axis 3.0.\n"
    )

    prompt = f"""You are a job evaluation assistant. Evaluate this job for the candidate and return ONLY valid JSON.
{resume_block}{north_star_block}
Job Title: {payload.jobTitle}
Company: {payload.company}
Job Description:
{payload.description[:3000]}

Ghost-Job Signals (use these facts when scoring Posting Legitimacy):
{signals_text}

Evaluate on exactly 6 axes. Return this JSON structure (no markdown, no extra text):
{{
  "overallGrade": "B+",
  "overallScore": 3.8,
  "verdict": "Worth applying",
  "axes": [
    {{
      "name": "CV Match",
      "grade": "A",
      "score": 4.5,
      "reasoning": "One sentence explanation."
    }},
    {{
      "name": "North Star Alignment",
      "grade": "B",
      "score": 3.5,
      "reasoning": "One sentence explanation."
    }},
    {{
      "name": "Compensation vs Market",
      "grade": "C",
      "score": 2.5,
      "reasoning": "One sentence explanation."
    }},
    {{
      "name": "Cultural Signals",
      "grade": "B+",
      "score": 3.8,
      "reasoning": "One sentence explanation."
    }},
    {{
      "name": "Red Flags",
      "grade": "A-",
      "score": 4.2,
      "reasoning": "One sentence explanation."
    }},
    {{
      "name": "Posting Legitimacy",
      "grade": "B",
      "score": 3.5,
      "reasoning": "One sentence explanation."
    }}
  ]
}}
Grades: A+, A, A-, B+, B, B-, C+, C, C-, D, F
Score: 1.0–5.0 (one decimal place)"""

    # ── 6. AI call ─────────────────────────────────────────
    from app.services.ai_provider_service import call_ai
    ai_result = call_ai(prompt, temperature=0.2, max_tokens=1200)

    if "error" in ai_result:
        await CreditsService.refund_credits(user_id, cost, "Job evaluation AI call failed")
        raise HTTPException(status_code=500, detail=ai_result["error"])

    # ── 7. Validate axes count (AI sometimes drops one) ───
    axes = ai_result.get("axes", [])
    if len(axes) != 6:
        await CreditsService.refund_credits(user_id, cost, "Job evaluation returned malformed response")
        raise HTTPException(
            status_code=500,
            detail="AI returned an unexpected evaluation format. Please try again."
        )

    # ── 8. Build evaluation result payload ─────────────────
    evaluation_result = {
        "overallGrade": ai_result.get("overallGrade", "C"),
        "overallScore": float(ai_result.get("overallScore", 3.0)),
        "verdict": ai_result.get("verdict", ""),
        "axes": axes,
        "cached": False,
    }

    # ── 9. Persist to cache ────────────────────────────────
    await mongo.job_evaluations.insert_one({
        "userId": user_id,
        "jobUrl": payload.jobUrl,
        "jobTitle": payload.jobTitle,
        "company": payload.company,
        "evaluationResult": evaluation_result,
        "ghostSignals": signals,
        "createdAt": datetime.utcnow(),
    })

    return {"data": evaluation_result}
