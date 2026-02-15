from fastapi import APIRouter, Depends, HTTPException, Query
from app.middleware.auth import get_current_user
from typing import Dict, List, Optional
from app.controllers.resume_controller import ResumeController
from app.models.resume.template import TemplateCreate, TemplateOut
from app.models.resume.user_resume import UserResumeCreate, UserResumeOut
from app.models.resume.schema import ResumeSchemaCreate, ResumeSchemaOut

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