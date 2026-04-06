# app/controllers/gemini_resume_controller.py
"""
Controller layer for Gemini-powered resume & job endpoints.
Credits are deducted BEFORE processing and refunded if processing fails.
Costs are DB-driven via credits_on_features collection.
"""

import logging
from fastapi import HTTPException, status

from app.services.credits_service import CreditsService
from app.services.resume_processor import (
    analyze_resume_match,
    extract_resume_from_text,
    tailor_resume,
    calculate_ats_score,
    parse_job_description,
    generate_cover_letter,
    check_resume_completeness,
)
from app.models.gemini.schemas import (
    AnalyzeResumeRequest, AnalyzeResumeResponse,
    ExtractResumeRequest, ExtractResumeResponse,
    TailorResumeRequest, TailorResumeResponse,
    AtsScoreRequest, AtsScoreResponse,
    ParseJobRequest, ParseJobResponse,
    GenerateCoverLetterRequest, GenerateCoverLetterResponse,
    CheckCompletenessRequest, CheckCompletenessResponse,
)
from app.services.incoming_resume_service import IncomingResumeService

logger = logging.getLogger(__name__)


async def process_analyze_resume(
    request: AnalyzeResumeRequest,
    current_user: str
) -> AnalyzeResumeResponse:
    cost = await CreditsService.get_feature_cost("analyze_resume")
    success, message = await CreditsService.deduct_credits(current_user, amount=cost, feature="analyze_resume")
    if not success:
        raise HTTPException(403, message or "Insufficient credits")

    try:
        result = analyze_resume_match(request.resume, request.jobDescription)
        result["creditsUsed"] = cost
        return AnalyzeResumeResponse(**result)
    except Exception:
        await CreditsService.refund_credits(current_user, cost, "Analyze resume failed")
        logger.exception("Analyze resume failed")
        raise HTTPException(500, "Processing failed")


async def process_extract_resume(
    request: ExtractResumeRequest,
    current_user: str
) -> ExtractResumeResponse:
    cost = await CreditsService.get_feature_cost("extract_resume")
    success, message = await CreditsService.deduct_credits(current_user, amount=cost, feature="extract_resume")
    if not success:
        raise HTTPException(403, message or "Insufficient credits")

    try:
        result = extract_resume_from_text(request.documentText)

        if "error" in result:
            await CreditsService.refund_credits(current_user, cost, "Resume extraction returned error")
            raise ValueError(result.get("message", "Gemini processing failed"))

        await IncomingResumeService.save_or_update(
            user_id=current_user,
            raw_input=request.documentText,
            extracted_data=result
        )

        result["creditsUsed"] = cost
        return ExtractResumeResponse(**result)

    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except Exception:
        await CreditsService.refund_credits(current_user, cost, "Extract resume failed")
        logger.exception("Extract resume failed")
        raise HTTPException(500, "Extraction failed")


async def process_tailor_resume(
    request: TailorResumeRequest,
    current_user: str
) -> TailorResumeResponse:
    cost = await CreditsService.get_feature_cost("tailor_resume")
    success, message = await CreditsService.deduct_credits(current_user, amount=cost, feature="tailor_resume")
    if not success:
        raise HTTPException(403, message or "Insufficient credits")

    try:
        result = tailor_resume(request.resume, request.jobDescription)
        result["creditsUsed"] = cost
        return TailorResumeResponse(**result)
    except Exception:
        await CreditsService.refund_credits(current_user, cost, "Tailor resume failed")
        logger.exception("Tailor resume failed")
        raise HTTPException(500, "Tailoring failed")


async def process_ats_score(
    request: AtsScoreRequest,
    current_user: str
) -> AtsScoreResponse:
    cost = await CreditsService.get_feature_cost("ats_score")
    success, message = await CreditsService.deduct_credits(current_user, amount=cost, feature="ats_score")
    if not success:
        raise HTTPException(403, message or "Insufficient credits")

    try:
        result = calculate_ats_score(request.resume, request.jobDescription)
        result["creditsUsed"] = cost
        return AtsScoreResponse(**result)
    except Exception:
        await CreditsService.refund_credits(current_user, cost, "ATS score failed")
        logger.exception("ATS score failed")
        raise HTTPException(500, "ATS calculation failed")


async def process_parse_job(
    request: ParseJobRequest,
    current_user: str
) -> ParseJobResponse:
    cost = await CreditsService.get_feature_cost("parse_job")
    success, message = await CreditsService.deduct_credits(current_user, amount=cost, feature="parse_job")
    if not success:
        raise HTTPException(403, message or "Insufficient credits")

    try:
        result = parse_job_description(request.jobDescription)
        result["creditsUsed"] = cost
        return ParseJobResponse(**result)
    except Exception:
        await CreditsService.refund_credits(current_user, cost, "Parse job failed")
        logger.exception("Parse job failed")
        raise HTTPException(500, "Job parsing failed")


async def process_generate_cover_letter(
    request: GenerateCoverLetterRequest,
    current_user: str
) -> GenerateCoverLetterResponse:
    cost = await CreditsService.get_feature_cost("cover_letter")
    success, message = await CreditsService.deduct_credits(current_user, amount=cost, feature="cover_letter")
    if not success:
        raise HTTPException(403, message or "Insufficient credits")

    try:
        result = generate_cover_letter(request.resume, request.jobDescription)
        result["creditsUsed"] = cost
        return GenerateCoverLetterResponse(**result)
    except Exception:
        await CreditsService.refund_credits(current_user, cost, "Cover letter generation failed")
        logger.exception("Cover letter generation failed")
        raise HTTPException(500, "Cover letter generation failed")


async def process_check_completeness(
    request: CheckCompletenessRequest,
    current_user: str
) -> CheckCompletenessResponse:
    cost = await CreditsService.get_feature_cost("check_completeness")
    success, message = await CreditsService.deduct_credits(current_user, amount=cost, feature="check_completeness")
    if not success:
        raise HTTPException(403, message or "Insufficient credits")

    try:
        result = check_resume_completeness(request.resume)
        result["creditsUsed"] = cost
        return CheckCompletenessResponse(**result)
    except Exception:
        await CreditsService.refund_credits(current_user, cost, "Completeness check failed")
        logger.exception("Completeness check failed")
        raise HTTPException(500, "Completeness check failed")
