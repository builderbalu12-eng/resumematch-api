# app/models/gemini/schemas.py
"""
Pydantic models specifically for the Gemini-powered resume/job endpoints.
These are SEPARATE from the resume template/schema models.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal, Any



# ── Common base for all requests ─────────────────────────────────────────────
class GeminiRequestBase(BaseModel):
    userCredits: int = Field(
        ...,
        ge=0,
        description="Current user credits (sent by frontend - informational only)"
    )


# ── Request Models ────────────────────────────────────────────────────────────

class AnalyzeResumeRequest(GeminiRequestBase):
    resume: str = Field(..., min_length=100, description="Full resume text")
    jobDescription: str = Field(..., min_length=100, description="Full job description text")


class ExtractResumeRequest(GeminiRequestBase):
    documentText: str = Field(..., min_length=100, description="Raw text extracted from uploaded document/PDF/image")


class TailorResumeRequest(GeminiRequestBase):
    resume: str = Field(..., min_length=100, description="Original resume text")
    jobDescription: str = Field(..., min_length=100, description="Target job description")


class AtsScoreRequest(GeminiRequestBase):
    resume: str = Field(..., min_length=100, description="Resume text")
    jobDescription: str = Field(..., min_length=100, description="Job description text")


class ParseJobRequest(GeminiRequestBase):
    jobDescription: str = Field(..., min_length=100, description="Full job posting text")


class GenerateCoverLetterRequest(GeminiRequestBase):
    resume: str = Field(..., min_length=100, description="Resume text")
    jobDescription: str = Field(..., min_length=100, description="Job description text")


class CheckCompletenessRequest(GeminiRequestBase):
    resume: str = Field(..., min_length=100, description="Resume text")


# ── Response Models ───────────────────────────────────────────────────────────

class AnalyzeResumeResponse(BaseModel):
    matchPercentage: int = Field(..., ge=0, le=100)
    atsScore: int = Field(..., ge=0, le=100)
    missingSkills: List[str]
    matchedSkills: List[str]
    strengths: List[str]
    weaknesses: List[str]
    suggestions: List[str]
    creditsUsed: Literal[1] = 1   # ← changed: removed const=True


class ExtractResumeResponse(BaseModel):
    contact: Dict[str, Optional[str]]
    summary: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    experience: List[Dict] = Field(default_factory=list)
    education: List[Dict] = Field(default_factory=list)
    projects: List[Dict] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    creditsUsed: Literal[2] = 2   # ← changed


class TailorResumeResponse(BaseModel):
    tailoredResume: str = Field(..., min_length=200)
    optimizationNotes: List[str]
    estimatedATSScore: int = Field(..., ge=0, le=100)
    creditsUsed: Literal[2] = 2   # ← changed


class AtsScoreResponse(BaseModel):
    atsScore: int = Field(..., ge=0, le=100)
    scoreBreakdown: Dict[Literal["formatting", "keywords", "structure", "relevance"], int]
    improvements: List[Dict[str, str]]  # issue, suggestion, impact
    topMissingKeywords: List[str]
    creditsUsed: Literal[1] = 1   # ← changed


class ParseJobResponse(BaseModel):
    jobTitle: Optional[str] = None
    company: Optional[str] = None
    requiredSkills: List[str] = Field(default_factory=list)
    preferredSkills: List[str] = Field(default_factory=list)
    experience: Optional[str] = None
    education: Optional[str] = None
    salaryRange: Optional[str] = None
    jobType: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    responsibilities: List[str] = Field(default_factory=list)
    benefits: Optional[List[str]] = None
    creditsUsed: Literal[1] = 1   # ← changed


class GenerateCoverLetterResponse(BaseModel):
    coverLetter: str = Field(..., min_length=200)
    creditsUsed: Literal[3] = 3   # ← changed


class CheckCompletenessResponse(BaseModel):
    completenessScore: int = Field(..., ge=0, le=100)
    sections: Dict[
        str,
        Dict[Literal["present", "score"], Any]  # present: bool, score: int
    ]
    missing: List[str]
    suggestions: List[str]
    creditsUsed: Literal[1] = 1   # ← changed


# Optional: wrapper for all responses (if you want consistent shape)
class GeminiApiResponse(BaseModel):
    data: Dict  # will contain the specific response model
    creditsUsed: int
    message: str = "Success"