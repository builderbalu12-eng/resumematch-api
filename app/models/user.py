from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

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

class UserUpdate(BaseModel):
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[EmailStr] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str