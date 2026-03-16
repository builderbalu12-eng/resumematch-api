# app/controllers/telegram_controller.py

import secrets
import qrcode
import io

from fastapi import HTTPException, status
from bson import ObjectId

from app.services.mongo import mongo
from app.services.telegram_service import telegram_service
from app.services.telegram.message_builder import message_builder
from app.models.telegram.schemas import TelegramWebhookPayload
from app.controllers.telegram.help import handle_help
from app.controllers.telegram.account import handle_credits, handle_status
from app.controllers.telegram.leads import handle_find_leads, handle_my_leads
from app.config import settings


class TelegramController:

    # ── Generate link token + deep link + QR ──────────
    async def get_link_url(self, user_id: str) -> dict:
        user = await mongo.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if user.get("telegram_linked"):
            return {
                "success": True,
                "linked":  True,
                "message": "Telegram already connected",
                "chat_id": user.get("telegram_chat_id"),
                "link":    None,
                "qr_url":  None,
            }

        token     = secrets.token_urlsafe(16)
        deep_link = f"https://t.me/{settings.telegram_bot_username}?start={token}"

        await mongo.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"telegram_link_token": token}}
        )

        qr_bytes = self._generate_qr_bytes(deep_link)

        return {
            "success":  True,
            "linked":   False,
            "message":  "Scan QR or click the link to connect Telegram",
            "link":     deep_link,
            "qr_bytes": qr_bytes,
        }

    # ── Check link status ─────────────────────────────
    async def get_status(self, user_id: str) -> dict:
        user = await mongo.users.find_one(
            {"_id": ObjectId(user_id)},
            {"telegram_linked": 1, "telegram_chat_id": 1}
        )
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return {
            "success": True,
            "linked":  user.get("telegram_linked", False),
            "chat_id": user.get("telegram_chat_id", None),
        }

    # ── Unlink Telegram from account ──────────────────
    async def unlink(self, user_id: str) -> dict:
        user = await mongo.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        await mongo.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "telegram_chat_id":    None,
                "telegram_linked":     False,
                "telegram_link_token": None,
            }}
        )
        return {"success": True, "message": "Telegram disconnected successfully"}

    # ── Webhook — main router ─────────────────────────
    async def handle_webhook(self, data: dict) -> dict:
        # ✅ Use typed schema
        payload = TelegramWebhookPayload(**data)
        message = payload.message
        if not message:
            return {"ok": True}

        chat_id = str(message.chat.id)
        text    = message.text or ""
        name    = message.chat.first_name or "there"

        if not text:
            return {"ok": True}

        cmd = text.split()[0].lower()

        # ── /start handled here (needs token logic) ────
        if cmd == "/start":
            await self._handle_start(chat_id, text, name)

        # ── All other commands → modular controllers ───
        elif cmd == "/help":
            await handle_help(chat_id)

        elif cmd == "/credits":
            await handle_credits(chat_id)

        elif cmd == "/status":
            await handle_status(chat_id)

        elif cmd == "/findleads":
            await handle_find_leads(chat_id, text)

        elif cmd == "/myleads":
            await handle_my_leads(chat_id, text)

        else:
            await telegram_service.send_message(
                chat_id,
                "❓ Unknown command. Type /help to see all commands."
            )

        return {"ok": True}

    # ── /start <token> ────────────────────────────────
    async def _handle_start(self, chat_id: str, text: str, name: str):
        parts = text.split()
        token = parts[1] if len(parts) > 1 else None

        if token:
            user = await mongo.users.find_one({"telegram_link_token": token})
            if user:
                await mongo.users.update_one(
                    {"_id": user["_id"]},
                    {
                        "$set":   {"telegram_chat_id": chat_id, "telegram_linked": True},
                        "$unset": {"telegram_link_token": ""}
                    }
                )
                await telegram_service.send_message(
                    chat_id,
                    f"✅ <b>Hey {name}! Account linked!</b>\n\n"
                    f"Type /help to see everything you can do 🚀"
                )
            else:
                await telegram_service.send_message(
                    chat_id,
                    "❌ <b>Invalid or expired link.</b>\n\n"
                    "Go back to the app → Connect Telegram → get a fresh link."
                )
        else:
            await telegram_service.send_message(
                chat_id,
                f"👋 <b>Hey {name}!</b>\n\n"
                f"To connect your account:\n"
                f"1. Open the app\n"
                f"2. Go to Profile\n"
                f"3. Click <b>Connect Telegram</b>\n"
                f"4. Scan QR or click the link\n\n"
                f"Then type /help to see all commands! 🎯"
            )

    # ── QR generator ──────────────────────────────────
    def _generate_qr_bytes(self, data: str) -> bytes:
        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


telegram_controller = TelegramController()