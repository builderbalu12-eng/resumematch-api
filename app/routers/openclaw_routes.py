from fastapi import APIRouter, Depends
from app.middleware.auth import get_current_user
from app.services.openclaw.notification_service import NotificationService
from pydantic import BaseModel

router = APIRouter(prefix="/api/openclaw", tags=["openclaw"])

class SendMsg(BaseModel):
    phone: str
    message: str

class ConvReq(BaseModel):
    phone: str

@router.post("/connect")
async def connect_whatsapp(current_user: str = Depends(get_current_user)):
    return await NotificationService.connect_whatsapp(current_user)

@router.post("/send")
async def send_msg(req: SendMsg, current_user: str = Depends(get_current_user)):
    return await NotificationService.send_message(current_user, req.phone, req.message)

@router.post("/conversation")
async def get_conv(req: ConvReq, current_user: str = Depends(get_current_user)):
    return await NotificationService.get_conversation(current_user, req.phone)

@router.get("/status")
async def get_status(current_user: str = Depends(get_current_user)):
    session = await mongo.openclaw_sessions.find_one({"user_id": current_user})
    if not session:
        return {"connected": False, "status": "never_connected"}
    return {
        "connected": session["status"] == "connected",
        "status": session["status"],
        "last_message": session.get("last_output", "No log"),
        "port": session.get("port")
    }