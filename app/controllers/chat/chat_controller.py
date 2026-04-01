from typing import Dict, Any, List, Optional
from app.services.chat.ai_chat_service import ai_chat_service
from app.services.chat.session_service import session_service
from app.models.chat.schemas import (
    ChatResponse, 
    ChatHistoryResponse, 
    NewSessionResponse,
    SessionListResponse
)


class ChatController:
    
    @staticmethod
    async def send_message(user_id: str, session_id: str, message: str) -> Dict[str, Any]:
        """
        Send a message and get AI response.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            message: User message
            
        Returns:
            Dict with response data
        """
        try:
            # Get session history for context
            session_history = await session_service.get_session_history(user_id, session_id)
            
            # Save user message
            await session_service.save_message(user_id, session_id, "user", message)
            
            # Process message with AI
            ai_result = await ai_chat_service.process_message(user_id, message, session_history)
            
            # Save assistant response
            await session_service.save_message(
                user_id, 
                session_id, 
                "assistant", 
                ai_result["response"], 
                ai_result["intent"]
            )
            
            # Format response
            response = ChatResponse(
                session_id=session_id,
                message=ai_result["response"],
                intent=ai_result["intent"]
            )
            
            return {
                "status": "success",
                "success": True,
                "message": "Message processed successfully",
                "data": response.dict()
            }
            
        except Exception as e:
            print(f"Chat controller error: {str(e)}")
            return {
                "status": "error",
                "success": False,
                "message": f"Failed to process message: {str(e)}",
                "data": None
            }
    
    @staticmethod
    async def get_history(user_id: str, session_id: str) -> Dict[str, Any]:
        """
        Get chat history for a session.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            
        Returns:
            Dict with chat history
        """
        try:
            messages = await session_service.get_session_history(user_id, session_id)
            
            response = ChatHistoryResponse(
                session_id=session_id,
                messages=messages,
                total_messages=len(messages)
            )
            
            return {
                "status": "success",
                "success": True,
                "message": "History retrieved successfully",
                "data": response.dict()
            }
            
        except Exception as e:
            print(f"Get history error: {str(e)}")
            return {
                "status": "error",
                "success": False,
                "message": f"Failed to retrieve history: {str(e)}",
                "data": None
            }
    
    @staticmethod
    async def new_session(user_id: str) -> Dict[str, Any]:
        """
        Create a new chat session.
        
        Args:
            user_id: User identifier
            
        Returns:
            Dict with new session data
        """
        try:
            session_id = await session_service.create_session(user_id)
            
            response = NewSessionResponse(
                session_id=session_id
            )
            
            return {
                "status": "success",
                "success": True,
                "message": "New session created successfully",
                "data": response.dict()
            }
            
        except Exception as e:
            print(f"New session error: {str(e)}")
            return {
                "status": "error",
                "success": False,
                "message": f"Failed to create session: {str(e)}",
                "data": None
            }
    
    @staticmethod
    async def delete_session(user_id: str, session_id: str) -> Dict[str, Any]:
        """
        Delete a chat session.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            
        Returns:
            Dict with deletion result
        """
        try:
            success = await session_service.delete_session(user_id, session_id)
            
            if success:
                return {
                    "status": "success",
                    "success": True,
                    "message": "Session deleted successfully",
                    "data": {"session_id": session_id}
                }
            else:
                return {
                    "status": "error",
                    "success": False,
                    "message": "Session not found or could not be deleted",
                    "data": None
                }
                
        except Exception as e:
            print(f"Delete session error: {str(e)}")
            return {
                "status": "error",
                "success": False,
                "message": f"Failed to delete session: {str(e)}",
                "data": None
            }
    
    @staticmethod
    async def get_all_sessions(user_id: str) -> Dict[str, Any]:
        """
        Get all sessions for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            Dict with all sessions data
        """
        try:
            sessions = await session_service.get_all_sessions(user_id)
            
            response = SessionListResponse(
                sessions=sessions,
                total_sessions=len(sessions)
            )
            
            return {
                "status": "success",
                "success": True,
                "message": "Sessions retrieved successfully",
                "data": response.dict()
            }
            
        except Exception as e:
            print(f"Get all sessions error: {str(e)}")
            return {
                "status": "error",
                "success": False,
                "message": f"Failed to retrieve sessions: {str(e)}",
                "data": None
            }


# Singleton instance
chat_controller = ChatController()
