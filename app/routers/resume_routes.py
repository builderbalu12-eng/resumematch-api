from fastapi import APIRouter, Depends, HTTPException, Query
from app.middleware.auth import get_current_user
from typing import Dict, List, Optional
from app.services.credits_service import CreditsService
from app.controllers.resume_controller import ResumeController
from app.models.resume.template import TemplateCreate, TemplateOut
from app.models.resume.user_resume import UserResumeCreate, UserResumeOut
from app.models.resume.schema import ResumeSchemaCreate, ResumeSchemaOut
from app.services.incoming_resume_service import IncomingResumeService

from app.controllers.gemini_resume_controller import (
    process_analyze_resume,
    process_extract_resume,
    process_tailor_resume,
    process_ats_score,
    process_parse_job,
    process_generate_cover_letter,
    process_generate_skills_roadmap,
    process_check_completeness,
    process_analyze_and_tailor,
)

from app.models.gemini.schemas import (
    AnalyzeResumeRequest, AnalyzeResumeResponse,
    ExtractResumeRequest, ExtractResumeResponse,
    TailorResumeRequest, TailorResumeResponse,
    AtsScoreRequest, AtsScoreResponse,
    ParseJobRequest, ParseJobResponse,
    GenerateCoverLetterRequest, GenerateCoverLetterResponse,
    SkillsRoadmapRequest, SkillsRoadmapResponse,
    CheckCompletenessRequest, CheckCompletenessResponse,
    AnalyzeAndTailorRequest, AnalyzeAndTailorResponse,
)

router = APIRouter(tags=["resume"])

# ── Admin / Template Management ──
@router.post("/admin/templates", response_model=dict)
async def create_template(
    template: TemplateCreate,
    current_user: str = Depends(get_current_user)
):
    return await ResumeController.create_template(template, current_user)

@router.get("/templates", response_model=dict)
async def list_public_templates(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(20, ge=1, le=100, description="Max items per page"),
    search: Optional[str] = Query(None, description="Search by name or template_id")
):
    # NO Depends(get_current_user) here
    return await ResumeController.list_public_templates(skip, limit, search)


@router.get("/templates/{template_id}", response_model=dict)
async def get_public_template(template_id: str):
    # NO Depends(get_current_user) here
    return await ResumeController.get_public_template(template_id)

@router.put("/admin/templates/{template_id}", response_model=dict)
async def update_template(
    template_id: str,
    update_data: dict,  # use dict for partial update (or create TemplateUpdate model)
    current_user: str = Depends(get_current_user)
):
    return await ResumeController.update_template(template_id, update_data, current_user)

@router.delete("/admin/templates/{template_id}", response_model=dict)
async def delete_template(
    template_id: str,
    current_user: str = Depends(get_current_user)
):
    return await ResumeController.delete_template(template_id, current_user)

# ── User Resumes ──
@router.post("/resumes", response_model=dict)
async def create_resume(
    data: UserResumeCreate,
    current_user: str = Depends(get_current_user)
):
    cost = await CreditsService.get_feature_cost("create_resume")
    if cost > 0:
        success, msg = await CreditsService.deduct_credits(current_user, amount=cost, feature="create_resume")
        if not success:
            raise HTTPException(status_code=403, detail=msg)
    return await ResumeController.create_user_resume(current_user, data)



# ── Public Template Endpoints (no auth required) ──

@router.get("/templates", response_model=dict)
async def list_public_templates(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(20, ge=1, le=100, description="Max items per page"),
    search: Optional[str] = Query(None, description="Search by name or template_id")
):
    """
    Public: List all active templates (paginated, searchable)
    No authentication needed
    """
    return await ResumeController.list_public_templates(skip, limit, search)


@router.get("/templates/{template_id}", response_model=dict)
async def get_public_template(template_id: str):
    """
    Public: Get full details of a single active template
    Useful for previewing layout before creating a resume
    No authentication needed
    """
    return await ResumeController.get_public_template(template_id)


# ── Admin Schema Management ──
@router.post("/admin/schemas", response_model=dict)
async def create_schema(
    schema: ResumeSchemaCreate,
    current_user: str = Depends(get_current_user)
):
    return await ResumeController.create_schema(schema, current_user)

@router.get("/admin/schemas", response_model=dict)
async def list_admin_schemas(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
):
    # For admin list (can include inactive later if needed)
    return await ResumeController.list_schemas(skip, limit, active_only=False)

@router.get("/admin/schemas/{schema_id}", response_model=dict)
async def get_admin_schema(
    schema_id: str,
    current_user: str = Depends(get_current_user)
):
    # Reuse public get but with auth check if needed
    return await ResumeController.get_schema(schema_id)

@router.put("/admin/schemas/{schema_id}", response_model=dict)
async def update_schema(
    schema_id: str,
    update_data: dict,
    current_user: str = Depends(get_current_user)
):
    return await ResumeController.update_schema(schema_id, update_data, current_user)

@router.delete("/admin/schemas/{schema_id}", response_model=dict)
async def delete_schema(
    schema_id: str,
    current_user: str = Depends(get_current_user)
):
    return await ResumeController.delete_schema(schema_id, current_user)

# ── Public Schemas List (no auth) ──
@router.get("/schemas", response_model=dict)
async def list_public_schemas(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None)
):
    """
    Public: List all available schemas (paginated, searchable)
    No authentication required
    """
    return await ResumeController.list_public_schemas(skip, limit, search)



# ── User Resume Endpoints (auth required) ──

@router.post("/resumes", response_model=dict)
async def create_resume(
    data: UserResumeCreate,
    current_user: str = Depends(get_current_user)
):
    cost = await CreditsService.get_feature_cost("create_resume")
    if cost > 0:
        success, msg = await CreditsService.deduct_credits(current_user, amount=cost, feature="create_resume")
        if not success:
            raise HTTPException(status_code=403, detail=msg)
    return await ResumeController.create_user_resume(current_user, data)


@router.get("/resumes", response_model=dict)
async def list_my_resumes(
    status: Optional[str] = Query(None, description="Filter by status e.g. draft"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: str = Depends(get_current_user)
):
    return await ResumeController.list_user_resumes(
        user_id=current_user,
        status=status,
        skip=skip,
        limit=limit
    )


@router.get("/resumes/{resume_id}", response_model=dict)
async def get_resume(
    resume_id: str,
    current_user: str = Depends(get_current_user)
):
    return await ResumeController.get_user_resume(current_user, resume_id)


@router.put("/resumes/{resume_id}", response_model=dict)
async def update_resume_content(
    resume_id: str,
    content_update: Dict,
    current_user: str = Depends(get_current_user)
):
    return await ResumeController.update_user_resume_content(current_user, resume_id, content_update)


@router.delete("/resumes/{resume_id}", response_model=dict)
async def delete_resume(
    resume_id: str,
    current_user: str = Depends(get_current_user)
):
    return await ResumeController.delete_user_resume(current_user, resume_id)


@router.post("/resumes/{resume_id}/generate")
async def generate_resume(
    resume_id: str,
    format: str = Query("docx", description="docx or pdf"),
    current_user: str = Depends(get_current_user)
):
    return await ResumeController.generate_resume(current_user, resume_id, format)



# --------------------------------- GEMINI ROUTES ----------------------------------


@router.post("/analyze-resume", response_model=AnalyzeResumeResponse)
async def gemini_analyze_resume(
    request: AnalyzeResumeRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Analyze how well a resume matches a job description
    Credits used: 1
    """
    return await process_analyze_resume(request, current_user)


@router.post("/extract-resume", response_model=ExtractResumeResponse)
async def gemini_extract_resume(
    request: ExtractResumeRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Extract structured resume data from raw document text
    Credits used: 2
    """
    return await process_extract_resume(request, current_user)


@router.post("/tailor-resume", response_model=TailorResumeResponse)
async def gemini_tailor_resume(
    request: TailorResumeRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Generate a tailored/optimized version of the resume for a job
    Credits used: 2
    """
    return await process_tailor_resume(request, current_user)


@router.post("/ats-score", response_model=AtsScoreResponse)
async def gemini_ats_score(
    request: AtsScoreRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Calculate ATS compatibility score + suggestions
    Credits used: 1
    """
    return await process_ats_score(request, current_user)


@router.post("/parse-job", response_model=ParseJobResponse)
async def gemini_parse_job(
    request: ParseJobRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Parse structured data from a job description
    Credits used: 1
    """
    return await process_parse_job(request, current_user)


@router.post("/generate-cover-letter", response_model=GenerateCoverLetterResponse)
async def gemini_generate_cover_letter(
    request: GenerateCoverLetterRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Generate a tailored cover letter based on resume + job
    Credits used: 3
    """
    return await process_generate_cover_letter(request, current_user)


@router.post("/skills-roadmap", response_model=SkillsRoadmapResponse)
async def gemini_skills_roadmap(
    request: SkillsRoadmapRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Generate a skills learning roadmap for top skill gaps.
    Credits used: 1
    """
    return await process_generate_skills_roadmap(request, current_user)


@router.post("/check-completeness", response_model=CheckCompletenessResponse)
async def gemini_check_completeness(
    request: CheckCompletenessRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Check how complete a resume is + suggestions for improvement
    Credits used: 1
    """
    return await process_check_completeness(request, current_user)


@router.post("/analyze-and-tailor", response_model=AnalyzeAndTailorResponse)
async def gemini_analyze_and_tailor(
    request: AnalyzeAndTailorRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Combined endpoint: extract job data + tailor resume + ATS score in one Gemini call.
    Used by the Chrome extension for maximum speed and reliability.
    Credits used: 3
    """
    return await process_analyze_and_tailor(request, current_user)


# ── Incoming Resume (Save + Read) ─────────────────────────────────────
@router.get("/incoming-resume", response_model=dict)
async def get_incoming_resume(
    current_user: str = Depends(get_current_user)
):
    """
    Get the latest incoming resume extraction for the current user.
    Returns the saved extracted_data (flexible JSON from Gemini).
    """
    data = await IncomingResumeService.get_latest(current_user)
    if not data:
        raise HTTPException(status_code=404, detail="No incoming resume found for this user")

    # Clean MongoDB _id
    data.pop("_id", None)
    return data