from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime

PIPELINE_STAGES = {
    "evaluated", "applied", "responded", "contacted",
    "interview", "offer", "rejected", "discarded"
}


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
    # Tracker fields
    pipelineStage: str = "evaluated"
    notes: str = ""
    followUpDate: Optional[str] = None
    evaluationGrade: str = ""
    evaluationScore: float = 0.0
    compensationNotes: str = ""

    @field_validator("pipelineStage")
    @classmethod
    def validate_pipeline_stage(cls, v: str) -> str:
        if v not in PIPELINE_STAGES:
            raise ValueError(f"pipelineStage must be one of: {', '.join(sorted(PIPELINE_STAGES))}")
        return v


class ApplicationRecordUpdate(BaseModel):
    pipelineStage: Optional[str] = None
    notes: Optional[str] = None
    followUpDate: Optional[str] = None
    evaluationGrade: Optional[str] = None
    evaluationScore: Optional[float] = None
    compensationNotes: Optional[str] = None

    @field_validator("pipelineStage")
    @classmethod
    def validate_pipeline_stage(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PIPELINE_STAGES:
            raise ValueError(f"pipelineStage must be one of: {', '.join(sorted(PIPELINE_STAGES))}")
        return v


class ApplicationRecordOut(ApplicationRecordCreate):
    id: Optional[str] = Field(None, alias="_id")
    userId: str
    createdAt: datetime

    class Config:
        populate_by_name = True
