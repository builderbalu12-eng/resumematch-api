from pydantic import BaseModel, Field
from typing import List, Optional, Any


# ─────────────────────────────────────────────────────────────
# REQUEST — POST /api/jobs/recommend
# resume_id REMOVED — backend fetches it automatically
# ─────────────────────────────────────────────────────────────
class JobRecommendRequest(BaseModel):
    search_term:      str            = Field(...,    example="Full Stack Developer")
    location:         str            = Field(...,    example="Bangalore, India")
    sites:            List[str]      = Field(default=["indeed", "linkedin", "google"])
    is_remote:        Optional[bool] = Field(default=None)
    results_per_site: int            = Field(default=25,  ge=5,  le=50)
    hours_old:        int            = Field(default=72,  ge=1)
    include_naukri:   bool           = Field(default=True)
    naukri_pages:     int            = Field(default=2,   ge=1,  le=10)
    top_n:            int            = Field(default=10,  ge=1,  le=20)


# ─────────────────────────────────────────────────────────────
# JOB CARD — single job item returned in responses
# ─────────────────────────────────────────────────────────────
class JobCard(BaseModel):
    site:                str            = ""
    title:               str            = ""
    company:             str            = ""
    location:            str            = ""
    experience:          str            = ""
    salary:              str            = ""
    job_type:            str            = ""
    is_remote:           Optional[bool] = None
    job_url:             str            = ""
    date_posted:         str            = ""
    description:         str            = ""
    description_summary: str            = ""
    fit_score:           int            = 0
    best_role_label:     str            = ""
    matched_keywords:    List[str]      = Field(default_factory=list)
    missing_keywords:    List[str]      = Field(default_factory=list)
    reasoning:           str            = ""
    risk_flags:          List[str]      = Field(default_factory=list)

    class Config:
        extra = "allow"   # allow extra fields from Gemini/scraper without breaking


# ─────────────────────────────────────────────────────────────
# RESPONSE — POST /api/jobs/recommend
# ─────────────────────────────────────────────────────────────
class JobRecommendResponse(BaseModel):
    success:        bool       = True
    list_id:        str        = ""
    total_scraped:  int        = 0
    total_returned: int        = 0
    jobs:           List[JobCard] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# JOB LIST META — one item in the sidebar list
# ─────────────────────────────────────────────────────────────
class JobListMeta(BaseModel):
    list_id:     str = ""
    resume_id:   str = ""
    search_term: str = ""
    location:    str = ""
    total_jobs:  int = 0
    created_at:  str = ""


# ─────────────────────────────────────────────────────────────
# RESPONSE — GET /api/jobs/lists
# ─────────────────────────────────────────────────────────────
class JobListsResponse(BaseModel):
    success: bool              = True
    total:   int               = 0
    lists:   List[JobListMeta] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# RESPONSE — GET /api/jobs/lists/{list_id}
# ─────────────────────────────────────────────────────────────
class JobListDetailResponse(BaseModel):
    success:     bool          = True
    list_id:     str           = ""
    resume_id:   str           = ""
    search_term: str           = ""
    location:    str           = ""
    total_jobs:  int           = 0
    created_at:  str           = ""
    jobs:        List[JobCard] = Field(default_factory=list)
