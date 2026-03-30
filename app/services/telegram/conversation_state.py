from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services.mongo import mongo


async def get_state(chat_id: str) -> Optional[Dict[str, Any]]:
    doc = await mongo.telegram_conversations.find_one({"chat_id": chat_id})
    if not doc:
        return None
    doc.pop("_id", None)
    return doc


async def set_state(
    chat_id: str,
    user_id: str,
    flow: str,
    step: str,
    draft: Optional[Dict[str, Any]] = None,
) -> None:
    now = datetime.now(timezone.utc)
    await mongo.telegram_conversations.update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id":    chat_id,
                "user_id":    user_id,
                "flow":       flow,
                "step":       step,
                "draft":      draft or {},
                "updated_at": now,
            }
        },
        upsert=True,
    )


async def clear_state(chat_id: str) -> None:
    await mongo.telegram_conversations.delete_one({"chat_id": chat_id})
