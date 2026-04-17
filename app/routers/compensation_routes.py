from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Any

from app.middleware.auth import get_current_user
from app.services.credits_service import CreditsService

router = APIRouter(tags=["Compensation"])


# ── Utility ────────────────────────────────────────────────────

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


# ── Pydantic models ─────────────────────────────────────────────

class CompensationRequest(BaseModel):
    role: str
    location: str
    yearsOfExperience: Optional[float] = None
    statedSalary: Optional[str] = None


# ── POST /api/compensation/research ─────────────────────────────

@router.post("/compensation/research", response_model=dict)
async def research_compensation(
    payload: CompensationRequest,
    current_user: Any = Depends(get_current_user),
):
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Deduct 2 credits before AI call
    cost = await CreditsService.get_feature_cost("compensation_research")
    if cost <= 0:
        cost = 2.0
    ok, msg = await CreditsService.deduct_credits(user_id, cost, "compensation_research")
    if not ok:
        raise HTTPException(status_code=402, detail=msg)

    yoe_text = f"{payload.yearsOfExperience} years of experience" if payload.yearsOfExperience is not None else "experience level unspecified"
    stated_text = f"The job listing states: {payload.statedSalary}" if payload.statedSalary else "No salary was stated in the job listing."

    prompt = f"""You are a compensation research assistant with knowledge of global salary benchmarks.

Role: {payload.role}
Location: {payload.location}
Experience: {yoe_text}
{stated_text}

Based on your training data for this role, location, and experience level, return ONLY valid JSON with this structure (no markdown, no extra text):
{{
  "currency": "USD",
  "salaryRange": {{
    "min": 80000,
    "median": 110000,
    "max": 140000
  }},
  "verdict": "at market",
  "verdictDetail": "One sentence: e.g. 'The stated salary is within the typical market range for this role.'",
  "rationale": "Two concise sentences explaining the market context for this role and location.",
  "disclaimer": "Salary estimates are approximate and based on training data. Verify on Glassdoor, Levels.fyi, or LinkedIn Salary for current figures."
}}

Verdict must be one of: "below market", "at market", "above market", "unknown"
If the stated salary is empty or cannot be assessed, set verdict to "unknown" and explain in verdictDetail.
Use the currency most common for this location (e.g. USD for USA, GBP for UK, INR for India).
Salary values should be annual total compensation in integers."""

    from app.services.ai_provider_service import call_ai
    result = call_ai(prompt, temperature=0.2, max_tokens=600)

    if "error" in result:
        await CreditsService.refund_credits(user_id, cost, "Compensation research AI call failed")
        raise HTTPException(status_code=500, detail=result.get("error", "AI call failed"))

    # Validate required keys
    required = {"currency", "salaryRange", "verdict", "rationale", "disclaimer"}
    if not required.issubset(result.keys()):
        await CreditsService.refund_credits(user_id, cost, "Compensation research returned malformed response")
        raise HTTPException(status_code=500, detail="AI returned an unexpected format. Please try again.")

    salary_range = result.get("salaryRange", {})
    if not {"min", "median", "max"}.issubset(salary_range.keys()):
        await CreditsService.refund_credits(user_id, cost, "Compensation research returned malformed salaryRange")
        raise HTTPException(status_code=500, detail="AI returned an unexpected format. Please try again.")

    return {
        "data": {
            "currency": result["currency"],
            "salaryRange": {
                "min": int(salary_range["min"]),
                "median": int(salary_range["median"]),
                "max": int(salary_range["max"]),
            },
            "verdict": result["verdict"],
            "verdictDetail": result.get("verdictDetail", ""),
            "rationale": result["rationale"],
            "disclaimer": result["disclaimer"],
        }
    }
