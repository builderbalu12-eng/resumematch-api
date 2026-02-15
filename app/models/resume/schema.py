from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from datetime import datetime

class SectionField(BaseModel):
    type: str
    required: bool = False

class SectionSchema(BaseModel):
    type: str = "object"
    fields: Optional[Dict[str, SectionField]] = None
    item: Optional[Dict] = None  # for arrays

class ResumeSchemaCreate(BaseModel):
    schema_id: str
    name: str
    description: Optional[str] = None
    required_sections: List[str] = []
    sections: Dict[str, SectionSchema] = {}

class ResumeSchemaOut(ResumeSchemaCreate):
    id: str = Field(..., alias="_id")
    version: int = 1
    created_at: datetime