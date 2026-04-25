# app/models/resume_ai/schemas.py
"""
Pydantic models for the Claude-powered resume/job endpoints.
These are SEPARATE from the resume template/schema models.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal, Any



# ── Common base for all requests ─────────────────────────────────────────────
class AIRequestBase(BaseModel):
    userCredits: int = Field(
        ...,
        ge=0,
        description="Current user credits (sent by frontend - informational only)"
    )


# ── Request Models ────────────────────────────────────────────────────────────

class AnalyzeResumeRequest(AIRequestBase):
    resume: str = Field(..., min_length=100, description="Full resume text")
    jobDescription: str = Field(..., min_length=100, description="Full job description text")


class ExtractResumeRequest(AIRequestBase):
    documentText: str = Field(..., min_length=100, description="Raw text extracted from uploaded document/PDF/image")


class TailorResumeRequest(AIRequestBase):
    resume: str = Field(..., min_length=100, description="Original resume text")
    jobDescription: str = Field(..., min_length=100, description="Target job description")


class AtsScoreRequest(AIRequestBase):
    resume: str = Field(..., min_length=100, description="Resume text")
    jobDescription: str = Field(..., min_length=100, description="Job description text")


class ParseJobRequest(AIRequestBase):
    jobDescription: str = Field(..., min_length=100, description="Full job posting text")


class GenerateCoverLetterRequest(AIRequestBase):
    resume: str = Field(..., min_length=100, description="Resume text")
    jobDescription: str = Field(..., min_length=100, description="Job description text")


class CheckCompletenessRequest(AIRequestBase):
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
    achievements: List[str] = Field(default_factory=list)
    publications: List[str] = Field(default_factory=list)
    hobbies: List[str] = Field(default_factory=list)
    customSections: Dict[str, str] = Field(default_factory=dict)
    creditsUsed: Literal[2] = 2   # ← changed


class SectionScore(BaseModel):
    """Per-section ATS match score. One entry per section the user has."""
    section: str = Field(..., description="Section name as it appears in the resume (Skills, Experience, Projects, etc.)")
    score: int = Field(..., ge=0, le=100, description="0–100 match score for this section vs the JD")
    jdKeywordsFound: int = Field(default=0, ge=0)
    jdKeywordsTotal: int = Field(default=0, ge=0)


class TailorResumeResponse(BaseModel):
    jobTitle: Optional[str] = None
    company: Optional[str] = None
    summary: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    experience: List[Dict] = Field(default_factory=list)
    projects: List[Dict] = Field(default_factory=list)
    education: List[Dict] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    achievements: List[str] = Field(default_factory=list)
    publications: List[str] = Field(default_factory=list)
    hobbies: List[str] = Field(default_factory=list)
    customSections: Dict[str, str] = Field(default_factory=dict)
    optimizationNotes: List[str] = Field(default_factory=list)
    keywordsAdded: List[str] = Field(default_factory=list)
    keywordsPresent: List[str] = Field(default_factory=list)
    sectionScores: List[SectionScore] = Field(default_factory=list)
    estimatedATSScore: int = Field(default=0, ge=0, le=100)
    originalAtsScore: int = Field(default=0, ge=0, le=100)
    creditsUsed: Literal[2] = 2


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


class SkillsRoadmapRequest(AIRequestBase):
    resume: str = Field(..., min_length=100, description="Resume text")
    jobDescription: str = Field(..., min_length=100, description="Job description text")


class SkillsRoadmapStep(BaseModel):
    label: str
    action: str


class SkillsRoadmapResource(BaseModel):
    type: str
    name: str


class SkillsRoadmapEntry(BaseModel):
    skill: str
    timeEstimate: str
    overview: str
    steps: List[SkillsRoadmapStep] = Field(default_factory=list)
    resources: List[SkillsRoadmapResource] = Field(default_factory=list)


class SkillsRoadmapResponse(BaseModel):
    skillGaps: List[str] = Field(default_factory=list)
    roadmaps: List[SkillsRoadmapEntry] = Field(default_factory=list)
    creditsUsed: Literal[1] = 1


class KeywordDistributionRequest(AIRequestBase):
    resume: str = Field(..., min_length=100, description="Resume text or JSON")
    jobDescription: str = Field(..., min_length=100, description="Job description text")


class KeywordDistributionCategory(BaseModel):
    name: Literal["Skills Relevant", "Experience Relevant", "Projects Relevant", "Others Relevant", "Not Relevant"]
    value: int = Field(..., ge=0)
    keywords: List[str] = Field(default_factory=list)


class KeywordDistributionResponse(BaseModel):
    categories: List[KeywordDistributionCategory]
    creditsUsed: Literal[1] = 1


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
class AIApiResponse(BaseModel):
    data: Dict  # will contain the specific response model
    creditsUsed: int
    message: str = "Success"


# ── Combined analyze + tailor (extension endpoint) ───────────────────────────

class AnalyzeAndTailorRequest(AIRequestBase):
    pageText: str = Field(..., min_length=50, description="Cleaned page text (HTML already stripped)")
    resume: Dict = Field(..., description="ResumeData JSON object")
    configuredSections: List[str] = Field(default_factory=list, description="Custom section names to generate")


class AnalyzeAndTailorResponse(BaseModel):
    jobTitle: str = ""
    company: str = ""
    location: str = ""
    jobDescription: str = ""
    requirements: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    tailoredSummary: str = ""
    tailoredExperience: List[Dict] = Field(default_factory=list)   # [{position, newBullets[]}]
    tailoredProjects: List[Dict] = Field(default_factory=list)     # [{title, newDescription}]
    tailoredSkillsOrder: List[str] = Field(default_factory=list)
    atsScore: int = Field(default=0, ge=0, le=100)
    matchPercentage: int = Field(default=0, ge=0, le=100)
    matchedKeywords: List[str] = Field(default_factory=list)
    missingKeywords: List[str] = Field(default_factory=list)
    improvements: List[str] = Field(default_factory=list)
    jobSummary: str = ""
    customSections: Dict[str, str] = Field(default_factory=dict)
    creditsUsed: int = 3