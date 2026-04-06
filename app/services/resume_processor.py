"""
All Gemini-powered resume/job processing logic.
SEPARATE from resume_generator.py (PDF only).
"""

import json
import logging
import base64
import io
from typing import Dict, Optional
import re

import google.generativeai as genai
import pdfplumber

from app.config import settings

logger = logging.getLogger(__name__)

# Global Gemini setup
genai.configure(api_key=settings.gemini_api_key)
MODEL = settings.gemini_model
GEN_MODEL = genai.GenerativeModel(MODEL)

logger.info(f"Gemini model loaded: {MODEL}")

# Safety limits
MAX_INPUT_CHARS = 100000000000000000000000
DEFAULT_MAX_OUTPUT_TOKENS = 8000


# ─────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────

def clean_json_response(text: str) -> str:
    """Remove markdown fences and trailing junk"""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    if text.startswith("```"):
        text = text[3:].strip()
    return text


# ─────────────────────────────────────────────────────────────
# Safe Gemini Caller (Prompts untouched)
# ─────────────────────────────────────────────────────────────

def call_gemini(
    prompt: str,
    temperature: float = 1.0,
    max_tokens: int = 8192,
    model: Optional[str] = None,
) -> Dict:

    if len(prompt) > MAX_INPUT_CHARS:
        logger.warning("Prompt truncated due to size limit")
        prompt = prompt[:MAX_INPUT_CHARS]

    for attempt in range(2):  # retry once if JSON fails
        try:
            gen_model = GEN_MODEL if model is None else genai.GenerativeModel(model)

            response = gen_model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=min(max_tokens, DEFAULT_MAX_OUTPUT_TOKENS),
                    response_mime_type="application/json",
                ),
            )

            if not response or not response.text:
                logger.error("Gemini returned empty response")
                continue

            raw_text = response.text.strip()
            cleaned = clean_json_response(raw_text)

            try:
                parsed = json.loads(cleaned)
                return parsed

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse failed (attempt {attempt+1})")
                if attempt == 1:
                    preview = cleaned[:2000] if cleaned else "N/A"
                    return {
                        "error": "invalid_json",
                        "message": "Gemini output was not valid JSON (likely truncated or malformed)",
                        "parse_error": str(e),
                        "raw_length": len(cleaned) if cleaned else 0,
                        "raw_preview": preview,
                    }

        except Exception as e:
            logger.exception("Gemini API call failed")
            return {
                "error": "gemini_api_error",
                "message": str(e),
            }

    return {"error": "unknown_error", "message": "Unexpected Gemini failure"}


# ─────────────────────────────────────────────────────────────
# Resume Extraction
# ─────────────────────────────────────────────────────────────
def extract_resume_from_text(document_text: str) -> Dict:
    # Step 1: Detect if input is base64 PDF
    is_base64_pdf = False
    original_input = document_text  # for logging

    document_text = document_text.strip()

    if (
        document_text.startswith("data:application/pdf")
        or document_text.startswith("JVBER")
        or document_text.startswith("[PDF_FILE_BASE64]")
    ):
        is_base64_pdf = True
        try:
            # ✅ REMOVE custom prefix FIRST
            if document_text.startswith("[PDF_FILE_BASE64]"):
                document_text = document_text.replace("[PDF_FILE_BASE64]", "", 1)

            # ✅ Remove data URI prefix if present
            if document_text.startswith("data:application/pdf"):
                document_text = document_text.split(",", 1)[1]

            # ✅ Decode safely
            pdf_bytes = base64.b64decode(document_text, validate=True)

            # ✅ Validate real PDF header
            if pdf_bytes[:4] != b"%PDF":
                return {"error": "invalid_pdf", "message": "Decoded file is not a valid PDF"}

            pdf_stream = io.BytesIO(pdf_bytes)

            extracted_text = ""
            with pdfplumber.open(pdf_stream) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        extracted_text += page_text + "\n\n"

            if not extracted_text.strip():
                return {"error": "pdf_text_empty", "message": "No readable text found in PDF"}

            document_text = extracted_text.strip()
            document_text = re.sub(r'([a-z])([A-Z])', r'\1 \2', document_text)
            document_text = re.sub(r'([a-zA-Z])(\()', r'\1 \2', document_text)
            document_text = re.sub(r'(\))([a-zA-Z])', r'\1 \2', document_text)
            document_text = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', document_text)
            document_text = re.sub(r'(\d)([a-zA-Z])', r'\1 \2', document_text)

        except Exception as e:
            logger.exception("PDF decoding/extraction failed")
            return {"error": "pdf_processing_failed", "message": str(e)}

    if len(document_text) > MAX_INPUT_CHARS:
        logger.warning("Resume text truncated due to size limit")
        document_text = document_text[:MAX_INPUT_CHARS]

    # Log what we're actually sending to Gemini
    logger.info(f"Input type: {'base64 PDF → extracted text' if is_base64_pdf else 'plain text'}")
    logger.info(f"Text length sent to Gemini: {len(document_text)} chars")
    logger.info(f"First 400 chars:\n{document_text[:400]}...")

    # Step 2: Now send clean text to Gemini
    prompt = f"""You are a strict resume parser. Extract ONLY information LITERALLY present in the text below.
DO NOT invent, hallucinate, assume or add any information. But just Clean and normalize the following text. Fix missing spaces. Do not change meaning.
If a field is missing → null or empty array.

Return ONLY this JSON — nothing else:

{{
  "contact": {{
    "name": string or null,
    "email": string or null,
    "phone": string or null,
    "location": string or null,
    "website": string or null,
    "linkedin": string or null,
    "github": string or null
  }},
  "summary": string or null,
  "skills": array of strings,
  "experience": array of objects with keys: title, company, location, startDate, endDate, isCurrentlyWorking (bool), description (array of strings),
  "education": array of objects with keys: institution, degree, field, graduationDate, gpa (string or null), achievements (array of strings),
  "projects": array of objects with keys: title, description, technologies (array), link, date,
  "certifications": array of strings
}}

Raw resume text:
{document_text}
"""

    return call_gemini(prompt, temperature=0.0, max_tokens=8192)


# ─────────────────────────────────────────────────────────────
# All 7 Processing Functions (UNCHANGED PROMPTS)
# ─────────────────────────────────────────────────────────────

def analyze_resume_match(resume: str, job_description: str) -> Dict:
    prompt = f"""You are a senior technical recruiter and ATS expert.
Compare the resume and job description.
Return **only valid JSON** with **no extra text or markdown** using these exact keys:

{{
  "matchPercentage": number 0-100,
  "atsScore": number 0-100,
  "missingSkills": array of strings,
  "matchedSkills": array of strings,
  "strengths": array of strings (2-5 items),
  "weaknesses": array of strings (2-5 items),
  "suggestions": array of strings (actionable improvements)
}}

Resume:
{resume}

Job Description:
{job_description}
"""
    return call_gemini(prompt, temperature=0.15)


def tailor_resume(resume: str, job_description: str) -> Dict:
    prompt = f"""You are an expert ATS optimization specialist and professional resume writer.
Your sole goal is to rewrite the resume to achieve the MAXIMUM possible ATS score against the given job description.

## Step 1 — Extract ALL keywords from the job description
Identify every required skill, tool, technology, certification, and key phrase.
Pay attention to exact terminology (e.g. "cross-functional collaboration", "CI/CD pipelines", "agile methodology").

## Step 2 — Rewrite the resume
- Incorporate EVERY required keyword and skill from Step 1 naturally into the resume
- Mirror the exact phrasing from the job description throughout — ATS systems match exact strings
- Place most relevant experience and skills first (reorder sections if needed)
- Quantify all achievements using numbers already present in the original (do not fabricate)
- Use standard ATS-safe section headers: SUMMARY, EXPERIENCE, SKILLS, EDUCATION, CERTIFICATIONS
- Add a dedicated SKILLS section listing all matched keywords if not already present
- NEVER use tables, columns, text boxes, or graphics — ATS parsers cannot read these
- Keep all original facts — do not invent experience, credentials, or employers

## Step 3 — Score
Count how many required keywords from Step 1 are naturally present in the rewritten resume.
Estimate a realistic ATS compatibility score from 0 to 100.

Return ONLY valid JSON with these exact keys:
{{
  "tailoredResume": "full optimized resume in plain text",
  "optimizationNotes": ["string", "string", ...],
  "estimatedATSScore": number
}}

Original Resume:
{resume}

Job Description:
{job_description}
"""
    result = call_gemini(prompt, temperature=0.0)

    # Cross-validate with the independent ATS scorer so the score is objective
    try:
        ats_result = calculate_ats_score(result.get("tailoredResume", ""), job_description)
        if ats_result.get("atsScore") is not None:
            result["estimatedATSScore"] = ats_result["atsScore"]
        if ats_result.get("scoreBreakdown"):
            result["scoreBreakdown"] = ats_result["scoreBreakdown"]
    except Exception:
        pass  # keep Gemini's self-reported score as fallback

    return result


def calculate_ats_score(resume: str, job_description: str) -> Dict:
    prompt = f"""You are an ATS optimization specialist.
Analyze this resume against the job description for ATS compatibility.

Return **only valid JSON** with these exact keys:

{{
  "atsScore": number 0-100,
  "scoreBreakdown": {{
    "formatting": number 0-100,
    "keywords": number 0-100,
    "structure": number 0-100,
    "relevance": number 0-100
  }},
  "improvements": array of objects, each with:
    "issue": string (short description),
    "suggestion": string (how to fix),
    "impact": string (estimated score increase, e.g. "+5–8 points")
  }},
  "topMissingKeywords": array of strings (5–10 most important missing terms)
}}

Resume:
{resume}

Job Description:
{job_description}
"""
    return call_gemini(prompt, temperature=0.15)


def parse_job_description(job_description: str) -> Dict:
    prompt = f"""You are a job description parser.
Extract structured information from this job posting.

Return **only valid JSON** with these exact keys (use null when information is missing):

{{
  "jobTitle": string or null,
  "company": string or null,
  "requiredSkills": array of strings,
  "preferredSkills": array of strings,
  "experience": string (e.g. "5+ years", "3–7 years"),
  "education": string or null,
  "salaryRange": string or null,
  "jobType": string or null (e.g. "Full-time", "Remote", "Hybrid"),
  "location": string or null,
  "description": string (short summary or first paragraph),
  "responsibilities": array of strings,
  "benefits": array of strings or null
}}

Full job description text:
{job_description}
"""
    return call_gemini(prompt, temperature=0.1)


def generate_cover_letter(resume: str, job_description: str) -> Dict:
    prompt = f"""You are a professional cover letter writer.
Write a compelling, concise cover letter (300–450 words) tailored to the job.

Use the resume to highlight relevant experience and achievements.
Incorporate keywords from the job description naturally.
Structure: 
1. Strong opening paragraph
2. 1–2 body paragraphs showing fit
3. Closing with call to action

Tone: confident, professional, enthusiastic.
Do NOT use generic phrases like "I am writing to apply for...".

Return **only valid JSON**:

{{
  "coverLetter": full cover letter text (use \\n for new lines),
  "wordCount": number,
  "tone": string ("professional", "confident", etc.)
}}

Resume:
{resume}

Job Description:
{job_description}
"""
    return call_gemini(prompt, temperature=0.35)


def check_resume_completeness(resume: str) -> Dict:
    prompt = f"""You are a resume completeness auditor.
Evaluate how complete and well-rounded this resume is for a mid-to-senior level professional role.

Return **only valid JSON** with these exact keys:

{{
  "completenessScore": number 0-100,
  "sections": {{
    "contact": {{"present": boolean, "score": number 0-100}},
    "summary": {{"present": boolean, "score": number 0-100}},
    "skills": {{"present": boolean, "score": number 0-100}},
    "experience": {{"present": boolean, "score": number 0-100}},
    "education": {{"present": boolean, "score": number 0-100}},
    "projects": {{"present": boolean, "score": number 0-100}},
    "certifications": {{"present": boolean, "score": number 0-100}},
    "portfolio_links": {{"present": boolean, "score": number 0-100}}
  }},
  "missing": array of strings (missing or weak sections/elements),
  "suggestions": array of strings (3–8 concrete recommendations)
}}

Resume text:
{resume}
"""
    return call_gemini(prompt, temperature=0.2)