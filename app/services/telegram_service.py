from typing import Any, Dict, List, Optional

import httpx
from app.config import settings

TELEGRAM_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

TELEGRAM_MAX_MESSAGE_LEN = 4096


class TelegramService:

    # ── Send plain text message ────────────────────────
    async def send_message(
        self,
        chat_id:    str,
        text:       str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        try:
            payload: Dict[str, Any] = {
                "chat_id":    chat_id,
                "text":       text,
                "parse_mode": parse_mode,
            }
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TELEGRAM_API}/sendMessage",
                    json=payload,
                    timeout=10,
                )
            return resp.status_code == 200
        except Exception as e:
            print(f"[Telegram] send_message failed: {e}")
            return False

    async def send_html_chunks(
        self,
        chat_id: str,
        parts: List[str],
        parse_mode: str = "HTML",
    ) -> None:
        for chunk in parts:
            if not chunk:
                continue
            if len(chunk) > TELEGRAM_MAX_MESSAGE_LEN:
                for i in range(0, len(chunk), TELEGRAM_MAX_MESSAGE_LEN - 200):
                    await self.send_message(
                        chat_id,
                        chunk[i : i + TELEGRAM_MAX_MESSAGE_LEN - 200],
                        parse_mode=parse_mode,
                    )
            else:
                await self.send_message(chat_id, chunk, parse_mode=parse_mode)

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
