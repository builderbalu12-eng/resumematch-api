from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Any, Optional

from app.models.job.listed_job import (
    JobRecommendRequest,
    JobRecommendResponse,
    JobListsResponse,
    JobListDetailResponse,
)
from app.controllers.job_controller import job_controller
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/jobs", tags=["Job Recommendations"])


def _extract_user_id(current_user: Any) -> str:
    """
    Safely extract user_id regardless of whether get_current_user
    returns a plain string or a dict.
    """
    if isinstance(current_user, str):
        return current_user
    elif isinstance(current_user, dict):
        return str(
            current_user.get("_id")
            or current_user.get("id")
            or current_user.get("user_id")
            or ""
        )
    return str(current_user)


# ─────────────────────────────────────────────────────────────
# POST /api/jobs/recommend
# Scrape jobs for a given resume_id + user → save + return ranked cards
# ─────────────────────────────────────────────────────────────
@router.post(
    "/recommend",
    response_model=JobRecommendResponse,
    summary="Scrape & rank jobs for a given resume_id using Claude",
)
async def recommend_jobs(
    payload: JobRecommendRequest,
    current_user: Any = Depends(get_current_user),
):
    """
    Flow:
    1. Validate user owns the resume (resume_id + user_id)
    2. Extract resume text from incoming_resumes
    3. Scrape LinkedIn, Indeed, Google, Naukri
    4. Claude ranks + summarizes each job
    5. Save results to job_lists (metadata) + listed_jobs (cards)
    6. Return ranked job cards
    """
    user_id = _extract_user_id(current_user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not extract user identity from token"
        )
    return await job_controller.recommend_jobs(user_id, payload)


# ─────────────────────────────────────────────────────────────
# GET /api/jobs/lists
# Get all past search sessions for current user (metadata only)
# ─────────────────────────────────────────────────────────────
@router.get(
    "/lists",
    response_model=JobListsResponse,
    summary="Get all job recommendation sessions for current user",
)
async def get_all_lists(
    current_user: Any = Depends(get_current_user),
):
    """
    Returns all past search sessions for the logged-in user.
    Each item shows: list_id, resume_id, search_term, location,
    total_jobs, created_at — NO job cards (lightweight).
    """
    user_id = _extract_user_id(current_user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not extract user identity from token"
        )
    return await job_controller.get_all_lists(user_id)


# ─────────────────────────────────────────────────────────────
# GET /api/jobs/lists/resume/{resume_id}
# Get all search sessions for a specific resume
# ─────────────────────────────────────────────────────────────
@router.get(
    "/lists/resume/{resume_id}",
    response_model=JobListsResponse,
    summary="Get all job recommendation sessions for a specific resume",
)
async def get_lists_by_resume(
    resume_id: str,
    current_user: Any = Depends(get_current_user),
):
    """
    Returns all past search sessions filtered by resume_id.
    Useful when a user has multiple resumes and wants to see
    sessions for a specific one.
    """
    user_id = _extract_user_id(current_user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not extract user identity from token"
        )
    return await job_controller.get_lists_by_resume(user_id, resume_id)


# ─────────────────────────────────────────────────────────────
# GET /api/jobs/lists/{list_id}
# Get a specific session with all job cards
# ─────────────────────────────────────────────────────────────
@router.get(
    "/lists/{list_id}",
    response_model=JobListDetailResponse,
    summary="Get full job cards for a specific recommendation session",
)
async def get_list_by_id(
    list_id: str,
    current_user: Any = Depends(get_current_user),
):
    """
    Returns full job cards for a specific list_id.
    Jobs are sorted by fit_score descending.
    Only accessible by the user who owns it.
    """
    user_id = _extract_user_id(current_user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not extract user identity from token"
        )
    return await job_controller.get_list_by_id(user_id, list_id)


# ─────────────────────────────────────────────────────────────
# DELETE /api/jobs/lists/{list_id}
# Delete a session and all its job cards
# ─────────────────────────────────────────────────────────────
@router.delete(
    "/lists/{list_id}",
    summary="Delete a job recommendation session and all its job cards",
)
async def delete_list(
    list_id: str,
    current_user: Any = Depends(get_current_user),
):
    """
    Deletes from BOTH collections:
    - job_lists  → the session metadata
    - listed_jobs → all job cards with this list_id
    """
    user_id = _extract_user_id(current_user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not extract user identity from token"
        )
    return await job_controller.delete_list(user_id, list_id)




# ─────────────────────────────────────────────────────────────
# GET /api/jobs/default
# Default job feed for users with no recommendations yet
# ─────────────────────────────────────────────────────────────
@router.get(
    "/default",
    summary="Default job feed — for users with no recommendations yet",
)
async def get_default_jobs(
    current_user: Any = Depends(get_current_user),
):
    """
    - If user already has personalized recommendations → returns has_recommendations: true
    - If user has NO recommendations yet → returns latest jobs from DB going back day by day
      until at least 10 jobs are collected.
    - Jobs are pulled globally (not tied to any specific user's resume).
    """
    user_id = _extract_user_id(current_user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not extract user identity from token"
        )
    return await job_controller.get_default_jobs(user_id)





# ─────────────────────────────────────────────────────────────
# GET /api/jobs/all
# Paginated list of ALL listed_jobs in DB with filters
# ─────────────────────────────────────────────────────────────
@router.get(
    "/all",
    summary="Get all listed jobs with pagination, search and filters",
)
async def get_all_listed_jobs(
    page:       int           = Query(default=1,           ge=1,    description="Page number"),
    limit:      int           = Query(default=10,          ge=1, le=100, description="Jobs per page (max 100)"),
    search:     str           = Query(default="",                   description="Search in title, company, location"),
    site:       str           = Query(default="",                   description="Filter by site: indeed, linkedin, naukri, google"),
    is_remote:  Optional[bool]= Query(default=None,                 description="Filter remote jobs"),
    min_score:  int           = Query(default=0,           ge=0, le=100, description="Minimum fit_score"),
    sort_by:    str           = Query(default="fit_score",          description="Sort field: fit_score | created_at | date_posted"),
    sort_order: str           = Query(default="desc",               description="Sort order: desc | asc"),
    current_user: Any         = Depends(get_current_user),
):
    user_id = _extract_user_id(current_user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not extract user identity from token"
        )
    return await job_controller.get_all_listed_jobs(
        page       = page,
        limit      = limit,
        search     = search,
        site       = site,
        is_remote  = is_remote,
        min_score  = min_score,
        sort_by    = sort_by,
        sort_order = sort_order,
    )
