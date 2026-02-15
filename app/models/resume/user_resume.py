from pydantic import BaseModel, Field
from typing import Dict, Optional
from datetime import datetime

class UserResumeCreate(BaseModel):
    template_id: str
    schema_id: str
    content: Dict

class UserResumeOut(BaseModel):
    id: str = Field(..., alias="_id")
    user_id: str
    resume_id: str
    template_id: str
    schema_id: str
    content: Dict
    created_at: datetime
    updated_at: Optional[datetime] = None