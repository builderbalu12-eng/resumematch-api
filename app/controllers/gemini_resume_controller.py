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
    analyze_and_tailor,
)
from app.models.gemini.schemas import (
    AnalyzeResumeRequest, AnalyzeResumeResponse,
    ExtractResumeRequest, ExtractResumeResponse,
    TailorResumeRequest, TailorResumeResponse,
    AtsScoreRequest, AtsScoreResponse,
    ParseJobRequest, ParseJobResponse,
    GenerateCoverLetterRequest, GenerateCoverLetterResponse,
    CheckCompletenessRequest, CheckCompletenessResponse,
    AnalyzeAndTailorRequest, AnalyzeAndTailorResponse,
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

        # Auto-save any contact URLs found in the resume to the user profile
        try:
            from app.services.mongo import mongo as _mongo
            from bson import ObjectId
            contact = result.get("contact", {}) or {}
            url_patch = {}
            if contact.get("website"):  url_patch["portfolio_url"] = contact["website"]
            if contact.get("linkedin"): url_patch["linkedin_url"]  = contact["linkedin"]
            if contact.get("github"):   url_patch["github_url"]    = contact["github"]
            if url_patch:
                await _mongo.users.update_one(
                    {"_id": ObjectId(current_user)},
                    {"$set": url_patch},
                )
        except Exception:
            pass  # non-blocking — profile enrichment failure should not fail extraction

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
        if "error" in result:
            await CreditsService.refund_credits(current_user, cost, "Tailor resume: Gemini error")
            raise HTTPException(503, "AI service temporarily unavailable. Credits refunded.")
        result["creditsUsed"] = cost
        return TailorResumeResponse(**result)
    except HTTPException:
        raise
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
        if "error" in result:
            await CreditsService.refund_credits(current_user, cost, "ATS score: Gemini error")
            raise HTTPException(503, "AI service temporarily unavailable. Credits refunded.")
        result["creditsUsed"] = cost
        return AtsScoreResponse(**result)
    except HTTPException:
        raise
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


async def process_analyze_and_tailor(
    request: AnalyzeAndTailorRequest,
    current_user: str
) -> AnalyzeAndTailorResponse:
    cost = await CreditsService.get_feature_cost("analyze_and_tailor")
    success, message = await CreditsService.deduct_credits(current_user, amount=cost, feature="analyze_and_tailor")
    if not success:
        raise HTTPException(403, message or "Insufficient credits")

    try:
        result = analyze_and_tailor(request.pageText, request.resume, request.configuredSections)
        if "error" in result:
            await CreditsService.refund_credits(current_user, cost, "Analyze and tailor: Gemini error")
            raise HTTPException(503, "AI service temporarily unavailable. Credits refunded.")
        result["creditsUsed"] = cost
        return AnalyzeAndTailorResponse(**result)
    except HTTPException:
        raise
    except Exception:
        await CreditsService.refund_credits(current_user, cost, "Analyze and tailor failed")
        logger.exception("Analyze and tailor failed")
        raise HTTPException(500, "Processing failed")


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
