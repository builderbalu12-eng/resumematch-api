from app.services.telegram_service import telegram_service
from app.services.telegram.message_builder import message_builder

async def handle_help(chat_id: str):
    await telegram_service.send_message(chat_id, message_builder.help())
