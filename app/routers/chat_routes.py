from fastapi import APIRouter, Depends, HTTPException, Query
from app.controllers.chat.chat_controller import chat_controller
from app.models.chat.schemas import SendMessageRequest
from app.middleware.auth import get_current_user


router = APIRouter(prefix="/chat", tags=["chat"])


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
