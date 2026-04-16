"""
Company Research endpoint — streams a 6-section pre-interview report via SSE.

Pattern:
  POST /api/interview/company-research  → starts background task, returns {job_id}
  GET  /api/interview/company-research/stream/{job_id}  → SSE stream

We reuse simhacli_service's queue + sse_generator infrastructure but drive it
from our own async task instead of a SimhaCLI subprocess.
"""

import asyncio
from datetime import datetime
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.middleware.auth import get_current_user
from app.services.mongo import mongo
from app.services.credits_service import CreditsService
from app.services import simhacli_service

router = APIRouter(tags=["Company Research"])


# ── Request model ──────────────────────────────────────────

class CompanyResearchRequest(BaseModel):
    company: str
    role: str


# ── Resume helper (mirrors job_evaluation_routes._get_resume_text) ──

async def _get_resume_summary(user_id: str) -> str:
    doc = await mongo.incoming_resumes.find_one(
        {"user_id": user_id}, sort=[("created_at", -1)]
    )
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
        return "\n".join(parts)[:1500]
    return (doc.get("raw_text") or "")[:1500]


# ── Markdown formatter ─────────────────────────────────────

def _sections_to_markdown(sections: list) -> list[str]:
    """Convert [{name, bullets}] → list of markdown lines."""
    lines: list[str] = []
    for section in sections:
        name = section.get("name", "Section")
        bullets = section.get("bullets", [])
        lines.append(f"## {name}")
        lines.append("")
        for bullet in bullets:
            lines.append(f"- {bullet}")
        lines.append("")
    return lines


# ── Background streaming task ──────────────────────────────

async def _stream_research(
    job_id: str,
    company: str,
    role: str,
    resume_summary: str,
):
    """
    Calls AI (in thread so it doesn't block the event loop), formats the
    result as markdown lines, and pushes them into the simhacli_service queue.
    """
    q = simhacli_service._queues.get(job_id)
    if q is None:
        return

    async def _finish(error_msg: Optional[str] = None):
        if error_msg:
            await q.put(f"ERROR: {error_msg}")
        await q.put(None)   # sentinel — sse_generator stops here

    resume_block = (
        f"Candidate background summary:\n{resume_summary}\n"
        if resume_summary
        else "Candidate background summary: Not provided.\n"
    )

    prompt = f"""You are a pre-interview research assistant. Research {company} for a candidate interviewing for {role}.

{resume_block}
Return a structured report with exactly 6 sections. For each section, provide 3–5 bullet points with specific, factual information.

Sections:
1. AI/ML Strategy — technical stack, LLM usage, published research, AI product direction
2. Recent Momentum — funding rounds, acquisitions, product launches, key hires (last 12 months)
3. Engineering Culture — deployment practices, remote/hybrid policy, team structure, engineering blog signals
4. Technical Challenges — known scaling issues, architecture decisions, engineering pain points
5. Market Position — main competitors, moat/differentiation, value proposition, market share signals
6. Personal Fit — based on the candidate's background above, how they map to {company}'s specific needs for {role}

Return ONLY valid JSON:
{{
  "sections": [
    {{
      "name": "AI/ML Strategy",
      "bullets": ["bullet 1", "bullet 2", "bullet 3"]
    }},
    {{
      "name": "Recent Momentum",
      "bullets": ["bullet 1", "bullet 2", "bullet 3"]
    }},
    {{
      "name": "Engineering Culture",
      "bullets": ["bullet 1", "bullet 2", "bullet 3"]
    }},
    {{
      "name": "Technical Challenges",
      "bullets": ["bullet 1", "bullet 2", "bullet 3"]
    }},
    {{
      "name": "Market Position",
      "bullets": ["bullet 1", "bullet 2", "bullet 3"]
    }},
    {{
      "name": "Personal Fit",
      "bullets": ["bullet 1", "bullet 2", "bullet 3"]
    }}
  ]
}}"""

    # Run the synchronous AI call in a thread so we don't block the event loop
    from app.services.ai_provider_service import call_ai
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: call_ai(prompt, temperature=0.3, max_tokens=2000),
        )
    except Exception as exc:
        await _finish(f"AI call failed: {exc}")
        return

    if "error" in result:
        await _finish(result["error"])
        return

    sections = result.get("sections", [])
    if not sections or len(sections) < 6:
        await _finish("AI returned an incomplete response. Please try again.")
        return

    # Stream the heading line-by-line so the client sees progress
    header = f"# Company Research: {company} — {role}"
    await q.put(header)
    await q.put("")

    for line in _sections_to_markdown(sections):
        await q.put(line)
        await asyncio.sleep(0)   # yield to event loop between lines

    await _finish()   # sends sentinel


# ── POST /api/interview/company-research ───────────────────

@router.post("/interview/company-research", response_model=dict)
async def start_company_research(
    body: CompanyResearchRequest,
    current_user: str = Depends(get_current_user),
):
    if not body.company.strip() or not body.role.strip():
        raise HTTPException(status_code=400, detail="company and role are required")

    # ── Credit deduction ──────────────────────────────────
    cost = await CreditsService.get_feature_cost("company_research")
    if cost <= 0:
        cost = 2.0
    ok, msg = await CreditsService.deduct_credits(current_user, cost, "company_research")
    if not ok:
        raise HTTPException(status_code=402, detail=msg)

    # ── Resume summary ────────────────────────────────────
    resume_summary = await _get_resume_summary(current_user)

    # ── Create queue + start background task ──────────────
    job_id = simhacli_service.new_job_id()
    simhacli_service._queues[job_id] = asyncio.Queue()

    async def _run():
        try:
            await _stream_research(job_id, body.company.strip(), body.role.strip(), resume_summary)
        except Exception as exc:
            q = simhacli_service._queues.get(job_id)
            if q:
                await q.put(f"ERROR: {exc}")
                await q.put(None)
            # Refund on unexpected failure
            await CreditsService.refund_credits(current_user, cost, "Company research task failed")

    asyncio.create_task(_run())

    return {"job_id": job_id, "message": "Company research started"}


# ── GET /api/interview/company-research/stream/{job_id} ───

@router.get("/interview/company-research/stream/{job_id}")
async def stream_company_research(job_id: str):
    async def event_gen():
        async for chunk in simhacli_service.sse_generator(job_id):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
