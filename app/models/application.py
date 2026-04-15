from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class ApplicationRecordCreate(BaseModel):
    jobTitle: str
    company: str
    location: str = ""
    jobUrl: str = ""
    atsScoreBefore: int = 0
    atsScoreAfter: int = 0
    matchPercentage: int = 0
    matchedKeywords: List[str] = Field(default_factory=list)
    missingKeywords: List[str] = Field(default_factory=list)
    status: str = "applied"


class ApplicationRecordOut(ApplicationRecordCreate):
    id: Optional[str] = Field(None, alias="_id")
    userId: str
    createdAt: datetime

    class Config:
        populate_by_name = True
