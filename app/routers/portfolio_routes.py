from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict

from app.middleware.auth import get_current_user
from app.services import portfolio_service, simhacli_service

router = APIRouter(tags=["portfolio"])


class GeneratePortfolioRequest(BaseModel):
    resume: Dict


@router.post("/portfolio/generate", response_model=dict)
async def generate_portfolio(
    request: GeneratePortfolioRequest,
    current_user: str = Depends(get_current_user),
):
    """Start portfolio generation. Returns job_id for SSE streaming."""
    if not request.resume:
        raise HTTPException(status_code=400, detail="Resume data is required")
    job_id = await portfolio_service.generate_portfolio(current_user, request.resume)
    return {"job_id": job_id, "message": "Portfolio generation started"}


@router.get("/portfolio/stream/{job_id}")
async def stream_portfolio(
    job_id: str,
):
    """SSE stream of SimhaCLI output. Subscribe after POST /portfolio/generate."""
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


@router.post("/portfolio/save-url", response_model=dict)
async def save_portfolio_url(
    payload: dict,
    current_user: str = Depends(get_current_user),
):
    """Frontend calls this when it detects a Vercel URL in the stream."""
    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    await portfolio_service.save_portfolio_url(current_user, url)
    return {"message": "Portfolio URL saved", "url": url}


@router.get("/portfolio/status", response_model=dict)
async def get_portfolio_status(
    current_user: str = Depends(get_current_user),
):
    """Get the user's existing deployed portfolio URL."""
    doc = await portfolio_service.get_portfolio(current_user)
    return {"portfolio": doc}
