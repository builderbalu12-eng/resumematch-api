# app/controllers/gemini_resume_controller.py
"""
Controller layer for Gemini-powered resume & job endpoints.
Credits are deducted ONLY after successful processing.
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
    try:
        result = analyze_resume_match(request.resume, request.jobDescription)
        result["creditsUsed"] = 1

        success, message = await CreditsService.deduct_credits(current_user, amount=1)
        if not success:
            raise HTTPException(403, message or "Credits deduction failed")

        return AnalyzeResumeResponse(**result)

    except Exception as e:
        logger.exception("Analyze resume failed")
        raise HTTPException(500, f"Processing failed: {str(e)}")

async def process_extract_resume(
    request: ExtractResumeRequest,
    current_user: str
) -> ExtractResumeResponse:
    try:
        # Run Gemini extraction
        result = extract_resume_from_text(request.documentText)

        # Handle possible error dict from call_gemini
        if "error" in result:
            raise ValueError(result.get("message", "Gemini processing failed"))

        # Auto-save to MongoDB (overwrite if exists)
        await IncomingResumeService.save_or_update(
            user_id=current_user,
            raw_input=request.documentText,    # save original input (base64 or text)
            extracted_data=result              # save whatever Gemini returned
        )

        # Deduct credits ONLY after successful extraction + save
        success, message = await CreditsService.deduct_credits(current_user, amount=2)
        if not success:
            raise HTTPException(403, message or "Credits deduction failed after processing")

        result["creditsUsed"] = 2
        return ExtractResumeResponse(**result)

    except ValueError as ve:
        # Bad extraction result (empty/invalid) → user error, no deduction
        raise HTTPException(400, str(ve))
    except Exception as e:
        logger.exception("Extract resume failed")
        # No deduction happened → credits safe
        raise HTTPException(500, f"Extraction failed: {str(e)}")

async def process_tailor_resume(
    request: TailorResumeRequest,
    current_user: str
) -> TailorResumeResponse:
    try:
        result = tailor_resume(request.resume, request.jobDescription)
        result["creditsUsed"] = 2

        success, message = await CreditsService.deduct_credits(current_user, amount=2)
        if not success:
            raise HTTPException(403, message or "Credits deduction failed")

        return TailorResumeResponse(**result)

    except Exception as e:
        logger.exception("Tailor resume failed")
        raise HTTPException(500, f"Tailoring failed: {str(e)}")


async def process_ats_score(
    request: AtsScoreRequest,
    current_user: str
) -> AtsScoreResponse:
    try:
        result = calculate_ats_score(request.resume, request.jobDescription)
        result["creditsUsed"] = 1

        success, message = await CreditsService.deduct_credits(current_user, amount=1)
        if not success:
            raise HTTPException(403, message or "Credits deduction failed")

        return AtsScoreResponse(**result)

    except Exception as e:
        logger.exception("ATS score failed")
        raise HTTPException(500, f"ATS calculation failed: {str(e)}")


async def process_parse_job(
    request: ParseJobRequest,
    current_user: str
) -> ParseJobResponse:
    try:
        result = parse_job_description(request.jobDescription)
        result["creditsUsed"] = 1

        success, message = await CreditsService.deduct_credits(current_user, amount=1)
        if not success:
            raise HTTPException(403, message or "Credits deduction failed")

        return ParseJobResponse(**result)

    except Exception as e:
        logger.exception("Parse job failed")
        raise HTTPException(500, f"Job parsing failed: {str(e)}")


async def process_generate_cover_letter(
    request: GenerateCoverLetterRequest,
    current_user: str
) -> GenerateCoverLetterResponse:
    try:
        result = generate_cover_letter(request.resume, request.jobDescription)
        result["creditsUsed"] = 3

        success, message = await CreditsService.deduct_credits(current_user, amount=3)
        if not success:
            raise HTTPException(403, message or "Credits deduction failed")

        return GenerateCoverLetterResponse(**result)

    except Exception as e:
        logger.exception("Cover letter generation failed")
        raise HTTPException(500, f"Cover letter generation failed: {str(e)}")


async def process_check_completeness(
    request: CheckCompletenessRequest,
    current_user: str
) -> CheckCompletenessResponse:
    try:
        result = check_resume_completeness(request.resume)
        result["creditsUsed"] = 1

        success, message = await CreditsService.deduct_credits(current_user, amount=1)
        if not success:
            raise HTTPException(403, message or "Credits deduction failed")

        return CheckCompletenessResponse(**result)

    except Exception as e:
        logger.exception("Completeness check failed")
        raise HTTPException(500, f"Completeness check failed: {str(e)}")



# async def process_extract_resume(
#     request: ExtractResumeRequest,
#     current_user: str
# ) -> ExtractResumeResponse:
#     try:
#         result = extract_resume_from_text(request.documentText)
#         print("---- RAW INPUT START ----")
#         print(result)
#         print("---- RAW INPUT END ----")

#         if "error" in result:
#             raise ValueError(result["message"])

#         result["creditsUsed"] = 2

#         success, message = await CreditsService.deduct_credits(current_user, amount=2)
#         if not success:
#             raise HTTPException(403, message or "Deduction failed after success")

#         return ExtractResumeResponse(**result)

#     except Exception as e:
#         # Refund if any deduction happened earlier (very rare)
#         await CreditsService.refund_credits(current_user, amount=2, reason="Resume extraction failed")
#         logger.exception("Extract resume failed")
#         raise HTTPException(500, f"Extraction failed: {str(e)}")