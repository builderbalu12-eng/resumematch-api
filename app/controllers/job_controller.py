from fastapi import HTTPException, status
from typing import Any, Optional

from app.services.credits_service import CreditsService
from app.models.job.listed_job import (
    JobRecommendRequest,
    JobRecommendResponse,
    JobListsResponse,
    JobListDetailResponse,
    JobCard,
    JobListMeta,
)
from app.services.job_recommendation_service import job_recommendation_service


class JobController:

    # ─────────────────────────────────────────────────
    # POST /recommend
    # resume_id auto-fetched from incoming_resumes
    # ─────────────────────────────────────────────────
    async def recommend_jobs(
        self,
        user_id: str,
        payload: JobRecommendRequest,
    ) -> JobRecommendResponse:

        # Step 0 — deduct credits before running job search
        cost = await CreditsService.get_feature_cost("find_jobs")
        if cost > 0:
            success, msg = await CreditsService.deduct_credits(user_id, amount=cost, feature="find_jobs")
            if not success:
                raise HTTPException(status_code=403, detail=msg)

        # Step 1 — auto fetch resume_id from DB
        try:
            resume_id = await job_recommendation_service.get_resume_id_for_user(user_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e)
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch resume: {str(e)}"
            )

        # Step 2 — run recommend flow with fetched resume_id
        try:
            result = await job_recommendation_service.recommend_jobs(
                user_id   = user_id,
                resume_id = resume_id,
                payload   = payload,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e)
            )
        except RuntimeError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error: {str(e)}"
            )

        return JobRecommendResponse(
            success        = result.get("success", True),
            list_id        = result.get("list_id", ""),
            total_scraped  = result.get("total_scraped", 0),
            total_returned = result.get("total_returned", 0),
            jobs           = [JobCard(**j) for j in result.get("jobs", [])],
        )

    # ─────────────────────────────────────────────────
    # GET /lists — all sessions for user
    # ─────────────────────────────────────────────────
    async def get_all_lists(self, user_id: str) -> JobListsResponse:
        try:
            result = await job_recommendation_service.get_all_lists(user_id)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )

        return JobListsResponse(
            success = result.get("success", True),
            total   = result.get("total", 0),
            lists   = [JobListMeta(**l) for l in result.get("lists", [])],
        )

    # ─────────────────────────────────────────────────
    # GET /lists/{list_id} — full job cards
    # ─────────────────────────────────────────────────
    async def get_list_by_id(
        self,
        user_id: str,
        list_id: str,
    ) -> JobListDetailResponse:
        try:
            result = await job_recommendation_service.get_list_by_id(
                user_id = user_id,
                list_id = list_id,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.get("error", "List not found")
            )

        return JobListDetailResponse(
            success     = True,
            list_id     = result.get("list_id", ""),
            resume_id   = result.get("resume_id", ""),
            search_term = result.get("search_term", ""),
            location    = result.get("location", ""),
            total_jobs  = result.get("total_jobs", 0),
            created_at  = result.get("created_at", ""),
            jobs        = [JobCard(**j) for j in result.get("jobs", [])],
        )

    # ─────────────────────────────────────────────────
    # DELETE /lists/{list_id}
    # ─────────────────────────────────────────────────
    async def delete_list(
        self,
        user_id: str,
        list_id: str,
    ) -> dict:
        try:
            result = await job_recommendation_service.delete_list(
                user_id = user_id,
                list_id = list_id,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.get("error", "List not found")
            )

        return result

    # ─────────────────────────────────────────────────
    # GET /default — default job feed
    # ─────────────────────────────────────────────────
    async def get_default_jobs(self, user_id: str) -> dict:
        try:
            return await job_recommendation_service.get_default_jobs(user_id)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )

    # ─────────────────────────────────────────────────
    # GET /all — paginated all jobs with filters
    # ─────────────────────────────────────────────────
    async def get_all_listed_jobs(
        self,
        page:       int,
        limit:      int,
        search:     str,
        site:       str,
        is_remote:  Optional[bool],
        min_score:  int,
        sort_by:    str,
        sort_order: str,
    ) -> dict:
        try:
            return await job_recommendation_service.get_all_listed_jobs(
                page       = page,
                limit      = limit,
                search     = search,
                site       = site,
                is_remote  = is_remote,
                min_score  = min_score,
                sort_by    = sort_by,
                sort_order = sort_order,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )


job_controller = JobController()
