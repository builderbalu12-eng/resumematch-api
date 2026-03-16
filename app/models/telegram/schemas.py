# app/models/telegram/schemas.py

from pydantic import BaseModel
from typing import Optional


class TelegramChat(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None


class TelegramMessage(BaseModel):
    message_id: int
    chat: TelegramChat
    text: Optional[str] = None
    date: Optional[int] = None


class TelegramWebhookPayload(BaseModel):
    update_id: int
    message: Optional[TelegramMessage] = None
