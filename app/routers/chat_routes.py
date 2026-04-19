from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict
from pydantic import BaseModel
from app.controllers.chat.chat_controller import chat_controller
from app.models.chat.schemas import SendMessageRequest
from app.middleware.auth import get_current_user
from app.services.credits_service import CreditsService
from bson import ObjectId


router = APIRouter(prefix="/chat", tags=["chat"])


class JobInterestRequest(BaseModel):
    job_title: str
    company: str
    job_url: str
    location: str


@router.post("/message")
async def send_message(
    request: SendMessageRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Send a message to the AI chat.
    
    - If session_id is provided, continues existing session
    - If session_id is None, creates new session automatically
    """
    try:
        # Deduct credits before processing
        cost = await CreditsService.get_feature_cost("ai_chat")
        if cost > 0:
            success, msg = await CreditsService.deduct_credits(current_user, amount=cost, feature="ai_chat")
            if not success:
                raise HTTPException(status_code=403, detail=msg)

        # Create new session if none provided
        if not request.session_id:
            session_result = await chat_controller.new_session(current_user)
            if not session_result["success"]:
                raise HTTPException(status_code=500, detail=session_result["message"])
            
            session_id = session_result["data"]["session_id"]
        else:
            session_id = request.session_id
        
        # Send message and get response
        result = await chat_controller.send_message(
            user_id=current_user,
            session_id=session_id,
            message=request.message
        )
        
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result["message"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/history")
async def get_history(
    session_id: str = Query(...),
    current_user: str = Depends(get_current_user)
):
    """
    Get chat history for a specific session.
    """
    try:
        result = await chat_controller.get_history(
            user_id=current_user,
            session_id=session_id
        )
        
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["message"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/session/new")
async def new_session(
    current_user: str = Depends(get_current_user)
):
    """
    Create a new chat session.
    """
    try:
        result = await chat_controller.new_session(current_user)
        
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result["message"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/session/{session_id}")
async def delete_session(
    session_id: str,
    current_user: str = Depends(get_current_user)
):
    """
    Delete a chat session.
    """
    try:
        result = await chat_controller.delete_session(
            user_id=current_user,
            session_id=session_id
        )
        
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["message"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/sessions/empty")
async def cleanup_empty_sessions(
    current_user: str = Depends(get_current_user)
):
    """Delete all sessions with no messages."""
    try:
        result = await chat_controller.cleanup_empty_sessions(current_user)
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/sessions")
async def get_all_sessions(
    current_user: str = Depends(get_current_user)
):
    """
    Get all chat sessions for the current user.
    """
    try:
        result = await chat_controller.get_all_sessions(current_user)

        if not result["success"]:
            raise HTTPException(status_code=500, detail=result["message"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/context-status", response_model=Dict)
async def get_context_status(
    current_user: str = Depends(get_current_user)
):
    """Return whether the user has an uploaded resume and job preferences set."""
    from app.services.mongo import mongo
    user = await mongo.users.find_one({"_id": ObjectId(current_user)})
    if not user:
        raise HTTPException(404, "User not found")

    has_resume = await mongo.incoming_resumes.find_one({"user_id": current_user}) is not None
    job_prefs = user.get("jobPreferences") or user.get("job_preferences") or {}
    job_prefs_set = bool(job_prefs.get("desired_role") or job_prefs.get("desiredRole"))

    return {
        "success": True,
        "data": {
            "has_resume": has_resume,
            "job_prefs_set": job_prefs_set,
        }
    }


@router.post("/job-interest", response_model=Dict)
async def save_job_interest(
    data: JobInterestRequest,
    current_user: str = Depends(get_current_user)
):
    """Save a job the user expressed interest in to their applications tracker."""
    from app.services.mongo import mongo
    import datetime

    application = {
        "user_id": current_user,
        "job_title": data.job_title,
        "company": data.company,
        "job_url": data.job_url,
        "location": data.location,
        "status": "evaluated",
        "source": "nova_chat",
        "created_at": datetime.datetime.utcnow().isoformat(),
        "updated_at": datetime.datetime.utcnow().isoformat(),
    }
    result = await mongo.applications.insert_one(application)
    return {
        "success": True,
        "data": {"application_id": str(result.inserted_id)}
    }
