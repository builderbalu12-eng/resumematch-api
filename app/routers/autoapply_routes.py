from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.middleware.auth import get_current_user
from app.services import autoapply_service, simhacli_service

router = APIRouter(tags=["auto-apply"])


class AutoApplyRequest(BaseModel):
    jobUrl: str
    name: str
    email: str
    phone: str = ""
    coverLetter: str = ""


@router.post("/autoapply/start", response_model=dict)
async def start_auto_apply(
    request: AutoApplyRequest,
    current_user: str = Depends(get_current_user),
):
    if not request.jobUrl or not request.email:
        raise HTTPException(status_code=400, detail="jobUrl and email are required")

    job_id = await autoapply_service.start_auto_apply(
        user_id=current_user,
        job_url=request.jobUrl,
        name=request.name,
        email=request.email,
        phone=request.phone,
        cover_letter=request.coverLetter,
    )
    return {"job_id": job_id, "message": "Auto-apply started"}


@router.get("/autoapply/stream/{job_id}")
async def stream_auto_apply(
    job_id: str,
):
    """SSE stream of Playwright actions."""
    async def event_gen():
        async for chunk in simhacli_service.sse_generator(job_id):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/autoapply/status/{job_id}", response_model=dict)
async def get_apply_status(
    job_id: str,
    current_user: str = Depends(get_current_user),
):
    return await autoapply_service.get_apply_status(job_id, current_user)
