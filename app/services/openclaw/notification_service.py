from app.scripts.openclaw.openclaw_bridge import OpenClawBridge
from app.services.mongo import mongo
from app.config import settings
from fastapi import HTTPException
from datetime import datetime
import asyncio
import shutil
import os


class NotificationService:

    @staticmethod
    def get_profile(user_id: str) -> str:
        clean_id = user_id.replace("-", "_").replace(".", "_")
        return f"rm_u_{clean_id}"

    @staticmethod
    async def ensure_openclaw_ready():
        """Ensure OpenClaw CLI is installed and GEMINI_API_KEY is set."""
        if not shutil.which("openclaw"):
            raise HTTPException(500, "OpenClaw not installed on this machine")
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key or ""

    @staticmethod
    async def connect_whatsapp(user_id: str) -> dict:
        """Connect a user's WhatsApp via OpenClaw, handle QR if needed."""
        await NotificationService.ensure_openclaw_ready()

        profile = NotificationService.get_profile(user_id)
        session = await mongo.openclaw_sessions.find_one({"user_id": user_id})

        # Already connected
        if session and session.get("status") == "connected":
            return {
                "success": True,
                "already_connected": True,
                "profile": profile,
                "port": session["port"]
            }

        # Assign port if new user
        if not session:
            agg = await mongo.openclaw_sessions.aggregate([
                {"$group": {"_id": None, "max_port": {"$max": "$port"}}}
            ]).to_list(1)
            last_port = agg[0]["max_port"] if agg else settings.base_openclaw_port - 1
            port = last_port + 1

            await mongo.openclaw_sessions.insert_one({
                "user_id": user_id,
                "profile": profile,
                "port": port,
                "status": "creating",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
        else:
            port = session["port"]

        # Start gateway
        print(f"[DEBUG] Starting gateway for {profile} on {port}")
        OpenClawBridge.start_gateway(profile, port)

        # Wait for gateway to become reachable and check status
        output = ""
        for _ in range(10):
            try:
                output = OpenClawBridge.trigger_status(profile)
                if "not reachable" not in output.lower():
                    break
            except Exception:
                pass
            await asyncio.sleep(1)

        lower_output = output.lower()
        status = "qr_pending"
        if any(word in lower_output for word in ["linked", "connected", "enabled", "ready"]):
            status = "connected"

        # Update session in MongoDB
        await mongo.openclaw_sessions.update_one(
            {"user_id": user_id},
            {"$set": {
                "status": status,
                "last_output": output[:2000],
                "updated_at": datetime.utcnow()
            }}
        )

        return {
            "success": True,
            "status": status,
            "needs_qr_scan": status == "qr_pending",
            "qr_or_message": output,
            "profile": profile,
            "port": port
        }

    @staticmethod
    async def send_message(user_id: str, phone: str, message: str):
        """Send WhatsApp message if user session is connected."""
        session = await mongo.openclaw_sessions.find_one({"user_id": user_id})
        if not session or session["status"] != "connected":
            raise HTTPException(400, "WhatsApp not connected. Call /connect first.")

        return {
            "success": True,
            "result": OpenClawBridge.send_message(
                session["profile"], phone, message
            )
        }

    @staticmethod
    async def get_conversation(user_id: str, phone: str):
        """Fetch WhatsApp conversation for a connected user."""
        session = await mongo.openclaw_sessions.find_one({"user_id": user_id})
        if not session or session["status"] != "connected":
            raise HTTPException(400, "WhatsApp not connected.")

        return {
            "success": True,
            "conversation": OpenClawBridge.get_conversation(
                session["profile"], phone
            )
        }