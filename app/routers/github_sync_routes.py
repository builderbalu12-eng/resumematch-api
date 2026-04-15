from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List

from app.middleware.auth import get_current_user
from app.services import github_sync_service, simhacli_service

router = APIRouter(tags=["github-sync"])


class ConnectGithubRequest(BaseModel):
    githubUsername: str


class SyncRequest(BaseModel):
    currentSkills: List[str] = []


class SuggestionActionRequest(BaseModel):
    suggestionId: str


@router.post("/github/connect", response_model=dict)
async def connect_github(
    request: ConnectGithubRequest,
    current_user: str = Depends(get_current_user),
):
    if not request.githubUsername.strip():
        raise HTTPException(status_code=400, detail="GitHub username is required")
    await github_sync_service.save_github_username(current_user, request.githubUsername.strip())
    return {"message": "GitHub username saved", "username": request.githubUsername}


@router.get("/github/connection", response_model=dict)
async def get_github_connection(current_user: str = Depends(get_current_user)):
    username = await github_sync_service.get_github_username(current_user)
    return {"githubUsername": username}


@router.post("/github/sync", response_model=dict)
async def start_sync(
    request: SyncRequest,
    current_user: str = Depends(get_current_user),
):
    username = await github_sync_service.get_github_username(current_user)
    if not username:
        raise HTTPException(status_code=400, detail="Connect GitHub username first")
    job_id = await github_sync_service.start_github_sync(
        current_user, username, request.currentSkills
    )
    return {"job_id": job_id, "message": "GitHub sync started"}


@router.get("/github/stream/{job_id}")
async def stream_sync(
    job_id: str,
):
    async def event_gen():
        async for chunk in simhacli_service.sse_generator(job_id):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/github/sync/{job_id}/complete", response_model=dict)
async def complete_sync(job_id: str, current_user: str = Depends(get_current_user)):
    """Called by frontend when SSE stream ends — parses output and saves suggestions."""
    suggestions = await github_sync_service.parse_and_save_suggestions(job_id)
    return {"message": "Sync complete", "suggestionsFound": len(suggestions)}


@router.get("/github/suggestions", response_model=dict)
async def get_suggestions(current_user: str = Depends(get_current_user)):
    suggestions = await github_sync_service.get_pending_suggestions(current_user)
    return {"suggestions": suggestions}


@router.post("/github/suggestions/{suggestion_id}/accept", response_model=dict)
async def accept_suggestion(
    suggestion_id: str,
    current_user: str = Depends(get_current_user),
):
    await github_sync_service.update_suggestion_status(suggestion_id, current_user, "accepted")
    return {"message": "Suggestion accepted"}


@router.post("/github/suggestions/{suggestion_id}/dismiss", response_model=dict)
async def dismiss_suggestion(
    suggestion_id: str,
    current_user: str = Depends(get_current_user),
):
    await github_sync_service.update_suggestion_status(suggestion_id, current_user, "dismissed")
    return {"message": "Suggestion dismissed"}
