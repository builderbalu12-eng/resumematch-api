from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"


class ChatMessage(BaseModel):
    role: MessageRole
    content: str
    intent: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatSession(BaseModel):
    user_id: str
    session_id: str
    messages: List[ChatMessage] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class NewSessionResponse(BaseModel):
    session_id: str
    created_at: datetime


class ChatResponse(BaseModel):
    session_id: str
    message: str
    intent: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SendMessageRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: List[ChatMessage]
    total_messages: int


class SessionListResponse(BaseModel):
    sessions: List[dict]
    total_sessions: int
