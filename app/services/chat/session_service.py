import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from app.services.mongo import mongo
from app.models.chat.schemas import ChatMessage, ChatSession


class SessionService:
    
    async def save_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
        action_type: Optional[str] = None,
        action_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Save a message to the chat session.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            role: Message role (user/assistant)
            content: Message content
            intent: Message intent (for assistant messages)
            
        Returns:
            bool: True if saved successfully
        """
        try:
            message = ChatMessage(
                role=role,
                content=content,
                intent=intent,
                action_type=action_type,
                action_data=action_data,
                timestamp=datetime.utcnow()
            )
            
            # Update session by pushing new message
            await mongo.chat_sessions.update_one(
                {"user_id": user_id, "session_id": session_id},
                {
                    "$push": {"messages": message.dict()},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            
            return True
            
        except Exception as e:
            print(f"Error saving message: {str(e)}")
            return False
    
    async def get_session_history(
        self, 
        user_id: str, 
        session_id: str, 
        limit: int = 20
    ) -> List[ChatMessage]:
        """
        Get chat history for a session.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            limit: Maximum number of messages to return
            
        Returns:
            List of ChatMessage objects
        """
        try:
            session = await mongo.chat_sessions.find_one(
                {"user_id": user_id, "session_id": session_id}
            )
            
            if not session:
                return []
            
            messages = session.get("messages", [])
            
            # Convert to ChatMessage objects and apply limit
            chat_messages = []
            for msg_data in messages[-limit:]:
                try:
                    chat_messages.append(ChatMessage(**msg_data))
                except Exception as e:
                    print(f"Error parsing message: {str(e)}")
                    continue
            
            return chat_messages
            
        except Exception as e:
            print(f"Error getting session history: {str(e)}")
            return []
    
    async def create_session(self, user_id: str) -> str:
        """
        Create a new chat session.
        
        Args:
            user_id: User identifier
            
        Returns:
            str: New session ID
        """
        try:
            session_id = str(uuid.uuid4())
            
            session = ChatSession(
                user_id=user_id,
                session_id=session_id,
                messages=[],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            await mongo.chat_sessions.insert_one(session.dict())
            
            return session_id
            
        except Exception as e:
            print(f"Error creating session: {str(e)}")
            raise
    
    async def get_all_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all sessions for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            List of session summaries
        """
        try:
            cursor = mongo.chat_sessions.find(
                {"user_id": user_id},
                {"session_id": 1, "created_at": 1, "updated_at": 1, "messages": {"$slice": 1}}
            ).sort("updated_at", -1)
            
            sessions = []
            async for session in cursor:
                # Get first message as preview
                messages = session.get("messages", [])
                preview = ""
                if messages:
                    preview = messages[0].get("content", "")[:50] + "..." if len(messages[0].get("content", "")) > 50 else messages[0].get("content", "")
                
                sessions.append({
                    "session_id": session.get("session_id"),
                    "created_at": session.get("created_at"),
                    "updated_at": session.get("updated_at"),
                    "message_count": len(messages),
                    "preview": preview
                })
            
            return sessions
            
        except Exception as e:
            print(f"Error getting all sessions: {str(e)}")
            return []
    
    async def delete_session(self, user_id: str, session_id: str) -> bool:
        """
        Delete a chat session.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            
        Returns:
            bool: True if deleted successfully
        """
        try:
            result = await mongo.chat_sessions.delete_one(
                {"user_id": user_id, "session_id": session_id}
            )
            
            return result.deleted_count > 0
            
        except Exception as e:
            print(f"Error deleting session: {str(e)}")
            return False
    
    async def cleanup_empty_sessions(self, user_id: str) -> int:
        """Delete all sessions with no messages for a user."""
        try:
            result = await mongo.chat_sessions.delete_many(
                {"user_id": user_id, "messages": {"$size": 0}}
            )
            return result.deleted_count
        except Exception as e:
            print(f"Error cleaning up empty sessions: {str(e)}")
            return 0

    async def get_session(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific session.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            
        Returns:
            Session data or None if not found
        """
        try:
            session = await mongo.chat_sessions.find_one(
                {"user_id": user_id, "session_id": session_id}
            )
            
            return session
            
        except Exception as e:
            print(f"Error getting session: {str(e)}")
            return None


# Singleton instance
session_service = SessionService()
