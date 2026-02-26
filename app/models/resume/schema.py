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






class ResumeJobRequest(BaseModel):
    resume: str = Field(..., min_length=50)
    jobDescription: str = Field(..., min_length=50)
    userCredits: int = Field(..., ge=0)   # frontend can send current value (informational)

class DocumentTextRequest(BaseModel):
    documentText: str = Field(..., min_length=50)
    userCredits: int = Field(..., ge=0)

class JobDescriptionRequest(BaseModel):
    jobDescription: str = Field(..., min_length=50)
    userCredits: int = Field(..., ge=0)

class ResumeOnlyRequest(BaseModel):
    resume: str = Field(..., min_length=50)
    userCredits: int = Field(..., ge=0)

# ── Response models (examples ── only partial, expand as needed)

class MatchAnalysisResponse(BaseModel):
    matchPercentage: int
    atsScore: int
    missingSkills: List[str]
    matchedSkills: List[str]
    strengths: List[str]
    weaknesses: List[str]
    suggestions: List[str]
    creditsUsed: int = 1

class ExtractedResumeResponse(BaseModel):
    contact: Dict[str, Optional[str]]
    summary: Optional[str]
    skills: List[str]
    experience: List[Dict]
    education: List[Dict]
    projects: List[Dict]
    certifications: List[str]
    creditsUsed: int = 2

# ... similarly for other endpoints