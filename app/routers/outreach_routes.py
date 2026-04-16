from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

from app.middleware.auth import get_current_user
from app.services.credits_service import CreditsService

router = APIRouter(tags=["Outreach"])

CONTACT_TYPE = Literal["hiring_manager", "recruiter", "peer", "interviewer"]


class OutreachRequest(BaseModel):
    contactName: str
    contactTitle: str
    contactType: CONTACT_TYPE
    company: str
    yourRole: str
    applicationId: Optional[str] = None


@router.post("/outreach/generate", response_model=dict)
async def generate_outreach(
    body: OutreachRequest,
    current_user: str = Depends(get_current_user),
):
    # ── Credit deduction ──────────────────────────────────
    cost = await CreditsService.get_feature_cost("outreach_generate")
    if cost <= 0:
        cost = 1.0
    ok, msg = await CreditsService.deduct_credits(current_user, cost, "outreach_generate")
    if not ok:
        raise HTTPException(status_code=402, detail=msg)

    prompt = f"""Write a personalized LinkedIn connection request message.

Contact: {body.contactName}, {body.contactTitle} at {body.company}
Contact type: {body.contactType}
Role I applied for: {body.yourRole}

Message style by contact type:
- hiring_manager: Emphasize the team's problem you can solve. Show you've researched their work.
- recruiter: Direct fit focus. Lead with the strongest CV hook.
- peer: Shared domain interest. Mention specific shared tech or challenge.
- interviewer: Reference their published work, talk, or article if you can infer it.

CRITICAL: The message MUST be under 300 characters including spaces. No hashtags. No emojis. Professional but warm.

Return ONLY valid JSON:
{{ "message": "your message here", "characterCount": 245 }}"""

    from app.services.ai_provider_service import call_ai
    result = call_ai(prompt, temperature=0.5, max_tokens=200)

    if "error" in result:
        await CreditsService.refund_credits(current_user, cost, "Outreach generation AI call failed")
        raise HTTPException(status_code=500, detail=result["error"])

    message = result.get("message", "").strip()
    if not message:
        await CreditsService.refund_credits(current_user, cost, "Outreach generation returned empty message")
        raise HTTPException(status_code=500, detail="AI returned an empty message. Please try again.")

    # Hard-cap at 300 chars regardless of what AI returns
    message = message[:300]

    return {
        "message": message,
        "characterCount": len(message),
    }
