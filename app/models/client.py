# app/models/client.py

from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime


class GeoLocation(BaseModel):
    type: str = "Point"
    coordinates: List[float]
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = "India"


class ClientCreate(BaseModel):
    name: str
    company: Optional[str] = None
    photo_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    website: Optional[str] = None
    category: str
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    status: str = "lead"
    location: Optional[GeoLocation] = None
    tags: Optional[List[str]] = []
    notes: Optional[str] = None
    address: Optional[str] = None
    social_links: Optional[Dict[str, str]] = {}


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    photo_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    website: Optional[str] = None
    category: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    status: Optional[str] = None
    location: Optional[GeoLocation] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    address: Optional[str] = None
    social_links: Optional[Dict[str, str]] = None


class ClientOut(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    owner_id: Optional[str] = None
    name: str
    company: Optional[str] = None
    photo_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    website: Optional[str] = None
    has_website: Optional[bool] = None
    address: Optional[str] = None
    rating: Optional[float] = None
    source: Optional[str] = None
    lat: Optional[float] = None          # ✅ ADDED
    lng: Optional[float] = None          # ✅ ADDED
    category: str
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    status: str = "lead"
    location: Optional[GeoLocation] = None
    tags: Optional[List[str]] = []
    notes: Optional[str] = None
    social_links: Optional[Dict[str, str]] = {}
    ai_insight: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
