import httpx
from app.config import settings

TELEGRAM_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


class TelegramService:

    # ── Send plain text message ────────────────────────
    async def send_message(
        self,
        chat_id:    str,
        text:       str,
        parse_mode: str = "HTML",
    ) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TELEGRAM_API}/sendMessage",
                    json={
                        "chat_id":    chat_id,
                        "text":       text,
                        "parse_mode": parse_mode,
                    },
                    timeout=10,
                )
            return resp.status_code == 200
        except Exception as e:
            print(f"[Telegram] send_message failed: {e}")
            return False

    # ── Send QR code image ─────────────────────────────
    async def send_photo_bytes(
        self,
        chat_id:     str,
        photo_bytes: bytes,
        filename:    str  = "qr.png",
        caption:     str  = "",
    ) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TELEGRAM_API}/sendPhoto",
                    data={
                        "chat_id": chat_id,
                        "caption": caption,
                    },
                    files={"photo": (filename, photo_bytes, "image/png")},
                    timeout=15,
                )
            return resp.status_code == 200
        except Exception as e:
            print(f"[Telegram] send_photo failed: {e}")
            return False

    # ── Send document / PDF ───────────────────────────
    async def send_document_bytes(
        self,
        chat_id:    str,
        file_bytes: bytes,
        filename:   str,
        caption:    str = "",
    ) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TELEGRAM_API}/sendDocument",
                    data={
                        "chat_id": chat_id,
                        "caption": caption,
                    },
                    files={"document": (filename, file_bytes, "application/pdf")},
                    timeout=30,
                )
            return resp.status_code == 200
        except Exception as e:
            print(f"[Telegram] send_document failed: {e}")
            return False


telegram_service = TelegramService()
