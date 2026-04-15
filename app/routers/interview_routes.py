from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List

from app.middleware.auth import get_current_user
from app.services import interview_service, simhacli_service

router = APIRouter(tags=["interview"])


class InterviewPrepRequest(BaseModel):
    company: str
    jobTitle: str
    matchedKeywords: List[str] = Field(default_factory=list)
    resumeSummary: str = ""
    resumeSkills: List[str] = Field(default_factory=list)


@router.post("/interview/prep", response_model=dict)
async def start_interview_prep(
    request: InterviewPrepRequest,
    current_user: str = Depends(get_current_user),
):
    """Start interview Q&A generation. Returns job_id for SSE streaming."""
    if not request.company or not request.jobTitle:
        raise HTTPException(status_code=400, detail="company and jobTitle are required")

    job_id = await interview_service.generate_interview_prep(
        user_id=current_user,
        company=request.company,
        job_title=request.jobTitle,
        matched_keywords=request.matchedKeywords,
        resume_summary=request.resumeSummary,
        resume_skills=request.resumeSkills,
    )
    return {"job_id": job_id, "message": "Interview prep started"}


@router.get("/interview/stream/{job_id}")
async def stream_interview_prep(
    job_id: str,
):
    """SSE stream of SimhaCLI output for interview prep generation."""
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


@router.get("/interview/result/{job_id}", response_model=dict)
async def get_interview_result(
    job_id: str,
    current_user: str = Depends(get_current_user),
):
    """Get the generated markdown Q&A after SimhaCLI finishes."""
    content = await interview_service.get_prep_result(job_id)
    if content is None:
        # Also try the raw SimhaCLI output
        raw = simhacli_service.get_result(job_id)
        if raw:
            content = raw
        else:
            raise HTTPException(status_code=404, detail="Result not ready yet")
    return {"content": content}
