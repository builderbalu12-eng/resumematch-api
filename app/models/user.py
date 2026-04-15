from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


class JobPreferences(BaseModel):
    desired_role: str = ""
    preferred_location: str = ""
    work_type: str = "any"          # "any" | "remote" | "on-site"
    preferred_sites: List[str] = Field(default_factory=lambda: ["indeed", "linkedin", "google"])


class User(BaseModel):
    uid: Optional[str] = Field(None, alias="_id")
    firstName: str
    lastName: str
    email: EmailStr
    password: Optional[str] = None
    credits: float = 150.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    auth_provider: str = "local"
    google_id: Optional[str] = None
    telegram_chat_id:    Optional[str] = None
    telegram_linked:     bool          = False
    telegram_link_token: Optional[str] = None


class UserCreate(BaseModel):
    firstName: str
    lastName: str
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    uid: str = Field(alias="_id")
    firstName: str
    lastName: str
    email: EmailStr
    credits: float
    auth_provider: str
    telegram_linked:  bool          = False
    telegram_chat_id: Optional[str] = None
    has_payments:     bool          = False    # ✅ added
    is_admin:         bool          = False

    class Config:
        populate_by_name = True


class UserUpdate(BaseModel):
    firstName: Optional[str] = None
    lastName:  Optional[str] = None
    # email is NOT here — email cannot be changed ever


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str
    confirm_password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
