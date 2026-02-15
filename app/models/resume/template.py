from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime

class Margins(BaseModel):
    top: float = 0.5
    bottom: float = 0.5
    left: float = 0.75
    right: float = 0.75

class TemplateCreate(BaseModel):
    template_id: str
    name: str
    description: Optional[str] = None
    layout: str = "1-column"
    page_size: str = "A4"
    margins: Margins = Margins()
    primary_color: str = "#2c3e50"
    secondary_color: str = "#7f8c8d"
    header_alignment: str = "left"
    ats_optimized: bool = True
    section_order: List[str] = ["personal_info", "experience", "education", "skills"]

class TemplateOut(TemplateCreate):
    id: str = Field(..., alias="_id")
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}