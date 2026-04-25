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

# Startup defaults — overridden immediately by init_gemini_config() in main.py
genai.configure(api_key=settings.gemini_api_key)
MODEL = settings.gemini_model

# Lazy import to avoid circular imports — used by call_ai() in ai_provider_service
def _call_ai(prompt, temperature=1.0, max_tokens=8192, model=None):
    from app.services.ai_provider_service import call_ai
    return call_ai(prompt, temperature=temperature, max_tokens=max_tokens, model=model)

logger.info(f"Gemini model loaded: {MODEL}")

# Safety limits
MAX_INPUT_CHARS = 100_000        # ~100k chars is ample for any resume/JD
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

    # Use the sync active config populated at startup (and refreshed on each admin save).
    try:
        from app.services.gemini_config_service import get_active_config_sync
        cfg = get_active_config_sync()
        genai.configure(api_key=cfg["api_key"])
        active_model = model or cfg["model"]
    except Exception as e:
        logger.warning(f"Could not load live Gemini config, using .env defaults: {e}")
        active_model = model or MODEL

    for attempt in range(2):  # 1 retry for JSON parse failures only
        try:
            gen_model = genai.GenerativeModel(active_model)

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
            err_msg = str(e)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "quota" in err_msg.lower():
                logger.error(f"Rate limit hit on model {active_model}. Switch to a higher-RPM model in admin panel.")
                return {"error": "gemini_api_error", "message": err_msg}
            logger.exception("Gemini API call failed")
            return {"error": "gemini_api_error", "message": err_msg}

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

    return _call_ai(prompt, temperature=0.0, max_tokens=8192)


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
    return _call_ai(prompt, temperature=0.15)


def tailor_resume(resume: str, job_description: str) -> Dict:
    prompt = f"""You are an expert ATS optimization specialist and professional resume writer.
Your goal is to tailor this resume for MAXIMUM ATS compatibility against the given job description.

## ABSOLUTE RULES — DO NOT VIOLATE
1. **STRICT SECTION PRESERVATION.** Return EXACTLY the sections the user gave you. Do NOT invent new sections. Do NOT merge sections. Do NOT move bullets between sections — a Project bullet must stay in `projects`, never under `experience`. An Education line must stay in `education`. Custom sections like "Volunteering" must stay in `customSections`.
2. **Section presence is faithful.** If the input resume has no Projects section, return `"projects": []`. If it has no Education, return `"education": []`. Do not fabricate sections to fill the JSON.
3. **Each section is enhanced individually** for ATS keyword density. Rewrite within a section, never across sections.
4. **No fabrication.** Keep all original facts — do not invent experience, employers, credentials, projects, or metrics.

## Step 1 — Extract ALL keywords from the job description
Identify every required skill, tool, technology, certification, and key phrase. Note exact terminology (e.g. "cross-functional collaboration", "CI/CD pipelines", "agile methodology") — ATS matches exact strings.

## Step 2 — Rewrite each section (only sections the user actually has)
- **summary**: 2–3 sentence professional summary emphasizing JD-relevant experience.
- **skills**: reorder by descending JD relevance; keep all originals.
- **experience**: rewrite bullets with JD keywords + exact JD phrasing; quantify only with numbers already in the original.
- **projects**: rewrite project descriptions to emphasize technologies/outcomes that match the JD. Each project keeps its title and any technologies the user listed.
- **education**: keep as-is unless the JD specifically calls for credentials the user has — then surface them.
- **certifications / achievements / publications / hobbies**: keep verbatim or lightly rephrase to add JD-relevant phrasing where honest.
- **customSections**: a free-form `Record<string, string>` map (e.g. {{"Volunteering": "...", "Languages": "..."}}). Preserve every key the user provided. Enhance the value text the same way as other sections.

## Step 3 — Per-section match score (drives the UI breakdown bars)
For each section the user has, compute a 0–100 match score = how strongly that section reflects the JD's keywords AFTER rewriting. Also count `jdKeywordsFound` (this section's matches against JD keyword list) and `jdKeywordsTotal` (total JD keywords). Skip sections the user does not have.

## Step 4 — Overall scores + diff
- `estimatedATSScore`: 0–100 overall ATS score AFTER tailoring.
- `originalAtsScore`: 0–100 estimated score for the ORIGINAL resume (before any rewrite).
- `keywordsAdded`: JD keywords newly surfaced by the rewrite (max 8).
- `keywordsPresent`: JD keywords already present in the original resume (max 8).
- `optimizationNotes`: 3–5 bullets describing the most impactful changes.

Return ONLY valid JSON. Use EXACT original job titles, company names, project titles so they can be matched:
{{
  "summary": "...",
  "skills": ["...", "..."],
  "experience": [
    {{
      "title": "EXACT original job title",
      "company": "EXACT original company",
      "description": ["bullet 1", "bullet 2", "..."]
    }}
  ],
  "projects": [
    {{
      "title": "EXACT original project title",
      "description": "rewritten 2-3 sentence description"
    }}
  ],
  "education": [
    {{ "degree": "...", "field": "...", "institution": "...", "graduationDate": "..." }}
  ],
  "certifications": ["...", "..."],
  "achievements": ["...", "..."],
  "publications": ["...", "..."],
  "hobbies": ["...", "..."],
  "customSections": {{"Section Name": "section body text"}},
  "jobTitle": "actual job title extracted from the JD",
  "company": "actual company extracted from the JD",
  "optimizationNotes": ["...", "..."],
  "keywordsAdded": ["...", "..."],
  "keywordsPresent": ["...", "..."],
  "sectionScores": [
    {{"section": "Skills",       "score": 0, "jdKeywordsFound": 0, "jdKeywordsTotal": 0}},
    {{"section": "Experience",   "score": 0, "jdKeywordsFound": 0, "jdKeywordsTotal": 0}}
  ],
  "estimatedATSScore": 0,
  "originalAtsScore": 0
}}

Reminder: only include sections the user actually has. Empty arrays / empty strings / empty objects for missing ones.

Original Resume:
{resume}

Job Description:
{job_description}
"""
    result = _call_ai(prompt, temperature=0.0)

    # Cross-validate the overall ATS score by rebuilding plain text and re-scoring objectively
    try:
        plain_parts = []
        if result.get("summary"):
            plain_parts.append(result["summary"])
        if result.get("skills"):
            plain_parts.append(" ".join(result["skills"]))
        for exp in result.get("experience", []):
            plain_parts.append(f"{exp.get('title', '')} {exp.get('company', '')}")
            plain_parts.extend(exp.get("description", []))
        for proj in result.get("projects", []):
            plain_parts.append(f"{proj.get('title', '')} {proj.get('description', '')}")
        for sec_name, sec_body in (result.get("customSections") or {}).items():
            plain_parts.append(f"{sec_name} {sec_body}")
        for c in result.get("certifications", []) or []:
            plain_parts.append(c)
        tailored_plain_text = "\n".join(plain_parts)

        ats_result = calculate_ats_score(tailored_plain_text, job_description)
        if ats_result.get("atsScore") is not None:
            result["estimatedATSScore"] = ats_result["atsScore"]
        if ats_result.get("scoreBreakdown"):
            result["scoreBreakdown"] = ats_result["scoreBreakdown"]
    except Exception:
        pass  # keep model's self-reported score as fallback

    return result


def calculate_ats_score(resume: str, job_description: str) -> Dict:
    prompt = f"""You are an ATS optimization specialist.
Analyze this resume against the job description for ATS compatibility.

Return ONLY valid JSON:

{{
  "atsScore": number 0-100,
  "scoreBreakdown": {{
    "formatting": number 0-100,
    "keywords": number 0-100,
    "structure": number 0-100,
    "relevance": number 0-100
  }},
  "improvements": [
    {{"issue": "short description", "suggestion": "how to fix", "impact": "+5-8 points"}}
  ],
  "topMissingKeywords": ["missing skill or tool", "another missing skill"]
}}

IMPORTANT for topMissingKeywords: Only include TECHNICAL SKILLS, TOOLS, TECHNOLOGIES, FRAMEWORKS, and DOMAIN KEYWORDS that are required in the job description but absent from the resume. Do NOT include:
- Locations or city names (e.g. Bengaluru, Mumbai)
- Years of experience (e.g. "3-5 years", "5+ years")
- Generic phrases (e.g. "team player", "communication skills")
- Education degrees
- Salary information

Resume:
{resume}

Job Description:
{job_description}
"""
    return _call_ai(prompt, temperature=0.15)


def parse_job_description(job_description: str) -> Dict:
    prompt = f"""Extract structured information from this job posting. Read carefully and pull out the ACTUAL values — do not use placeholder text.

Return ONLY this JSON (null if a field is genuinely missing):

{{
  "jobTitle": "the actual job title e.g. Senior Software Engineer",
  "company": "the actual company name e.g. Google",
  "requiredSkills": ["actual skill 1", "actual skill 2"],
  "preferredSkills": ["actual preferred skill 1"],
  "experience": "actual experience requirement e.g. 3-5 years",
  "education": "actual education requirement or null",
  "salaryRange": "salary if mentioned or null",
  "jobType": "Full-time / Part-time / Contract / Remote / Hybrid or null",
  "location": "actual city/country or null",
  "description": "1-2 sentence summary of what the role does",
  "responsibilities": ["actual responsibility 1", "actual responsibility 2"],
  "benefits": ["benefit 1"] or null
}}

IMPORTANT: Extract the REAL values from the text. Never use "Job Position", "Company", or any generic placeholder as a value.

Job posting:
{job_description}
"""
    return _call_ai(prompt, temperature=0.1)


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
    return _call_ai(prompt, temperature=0.35)


def generate_skills_roadmap(resume: str, job_description: str) -> Dict:
    prompt = f"""You are a career coach. Identify the top 2 skill gaps between this resume and job description, then generate a practical week-by-week learning roadmap for each.

Return ONLY valid JSON (no markdown, no extra text):

{{
  "skillGaps": ["skill1", "skill2"],
  "roadmaps": [
    {{
      "skill": "skill name",
      "timeEstimate": "~2-3 weeks",
      "overview": "Why this skill is critical for this role (2 sentences max).",
      "steps": [
        {{"label": "Days 1-2", "action": "Specific action with free resources mentioned by name."}},
        {{"label": "Days 3-5", "action": "Hands-on project step."}},
        {{"label": "Week 2", "action": "Deeper dive or build project."}},
        {{"label": "Week 3", "action": "Practice and apply to resume/portfolio."}}
      ],
      "resources": [
        {{"type": "YouTube", "name": "Video title and channel name"}},
        {{"type": "Course", "name": "Course name and platform"}},
        {{"type": "Documentation", "name": "Official docs title"}},
        {{"type": "Practice", "name": "Specific practice resource or project idea"}}
      ]
    }}
  ]
}}

Resume:
{resume}

Job Description:
{job_description}
"""
    return _call_ai(prompt, temperature=0.3)


def keyword_distribution(resume: str, job_description: str) -> Dict:
    """
    Categorize JD keywords by where they best match in the resume.
    Returns 5 fixed categories: Skills / Experience / Projects / Others / Not Relevant.
    Provider-agnostic via _call_ai().
    """
    prompt = f"""You are an ATS keyword analyzer.

Read the resume and job description below. Extract the most important keywords from the job
description (skills, tools, responsibilities, qualifications) and assign each to exactly ONE of
these 5 buckets based on where it best matches the resume:

1. "Skills Relevant"     — appears in the resume's Skills section.
2. "Experience Relevant" — appears in a job/experience description.
3. "Projects Relevant"   — appears in a project description.
4. "Others Relevant"     — appears elsewhere in the resume (education, certifications, etc.).
5. "Not Relevant"        — appears in the JD but is missing from the resume.

Return ONLY valid JSON, no markdown, no commentary:

{{
  "categories": [
    {{"name": "Skills Relevant",     "value": 0, "keywords": []}},
    {{"name": "Experience Relevant", "value": 0, "keywords": []}},
    {{"name": "Projects Relevant",   "value": 0, "keywords": []}},
    {{"name": "Others Relevant",     "value": 0, "keywords": []}},
    {{"name": "Not Relevant",        "value": 0, "keywords": []}}
  ]
}}

Rules:
- "value" is the count of keywords in that bucket.
- Each keyword goes in exactly one bucket — no duplicates across buckets.
- All 5 categories MUST be present, even if "value" is 0.
- Aim for 8–25 keywords total across all buckets.

Resume:
{resume}

Job Description:
{job_description}
"""
    return _call_ai(prompt, temperature=0.2)


def analyze_and_tailor(page_text: str, resume_json: dict, configured_sections: list) -> dict:
    """
    Single combined Gemini call: extract job data + tailor resume + ATS score.
    Mirrors the main branch's analyzeJobAndTailorResume single-prompt approach.
    Optional second call for custom sections.
    """
    import json as _json

    # Serialize resume to compact readable format for the prompt
    resume_str = _json.dumps(resume_json, indent=2)

    prompt = f"""Extract job details and tailor this resume for maximum ATS matching. Return ONLY valid JSON:

{{
  "jobTitle": "the actual job title extracted from the posting",
  "company": "the actual company name extracted from the posting",
  "location": "city/country or 'Not specified'",
  "jobDescription": "2-3 sentence summary of what the role does",
  "requirements": ["actual requirement 1", "actual requirement 2"],
  "skills": ["actual skill 1", "actual skill 2"],
  "tailoredSummary": "2-3 sentence professional summary emphasizing the candidate's most relevant experience for this specific role",
  "tailoredExperience": [
    {{
      "position": "EXACT original job title from resume",
      "newBullets": [
        "impact-driven bullet with quantifiable metric (%, numbers, improved, achieved, etc.) + JD keyword",
        "second bullet incorporating specific job keywords naturally",
        "third bullet showing direct alignment with job requirements"
      ]
    }}
  ],
  "tailoredProjects": [
    {{
      "title": "EXACT original project title from resume",
      "newDescription": "3-4 sentences: (1) what problem it solved, (2) technologies used especially those matching job requirements, (3) measurable impact/results with specific metrics"
    }}
  ],
  "tailoredSkillsOrder": ["most relevant skill to this job", "second most relevant", "all other skills in descending relevance"],
  "atsScore": 0-100,
  "atsMatchPercentage": 0-100,
  "matchedKeywords": ["keyword found in both resume and job"],
  "missingKeywords": ["important JD keyword not in resume"],
  "improvements": ["specific actionable improvement 1", "improvement 2"],
  "jobSummary": "one sentence: X% match for [job title] at [company]"
}}

ATS Scoring Instructions:
- Extract ALL skills and requirements from the job posting (aim for 15+ keywords)
- atsScore: base on skill match percentage; add bonus points for metrics in experience bullets and job title relevance; minimum 20
- Well-tailored resume (4+ relevant bullets, strong skill alignment): score 75-85+
- Excellent (5+ bullets with metrics, multiple relevant projects, strong summary): 80-90+
- tailoredExperience bullets must incorporate JD keywords naturally and include quantifiable metrics
- tailoredProjects: 3-4 detailed sentences with JD-relevant technologies and quantified results
- tailoredSkillsOrder: reorder existing resume skills by relevance to this job (do not add new skills)
- IMPORTANT: Use EXACT original job titles/project titles from the resume so matching works correctly

Job posting:
{page_text}

Resume:
{resume_str}"""

    result = _call_ai(prompt, temperature=0.0, max_tokens=8192)

    if "error" in result:
        return result

    # Normalize fields
    out = {
        "jobTitle": result.get("jobTitle", ""),
        "company": result.get("company", ""),
        "location": result.get("location", ""),
        "jobDescription": result.get("jobDescription", ""),
        "requirements": result.get("requirements", []),
        "skills": result.get("skills", []),
        "tailoredSummary": result.get("tailoredSummary", ""),
        "tailoredExperience": result.get("tailoredExperience", []),
        "tailoredProjects": result.get("tailoredProjects", []),
        "tailoredSkillsOrder": result.get("tailoredSkillsOrder", []),
        "atsScore": int(result.get("atsScore", 0)),
        "matchPercentage": int(result.get("atsMatchPercentage", result.get("matchPercentage", 0))),
        "matchedKeywords": result.get("matchedKeywords", []),
        "missingKeywords": result.get("missingKeywords", []),
        "improvements": result.get("improvements", []),
        "jobSummary": result.get("jobSummary", ""),
        "customSections": {},
    }

    # Optional second call: batch generate custom sections
    if configured_sections:
        job_title = out["jobTitle"]
        job_company = out["company"]
        job_skills = ", ".join(out["skills"][:10])
        candidate_name = resume_json.get("contact", {}).get("name", "Candidate")
        experience_summary = " | ".join(
            f"{e.get('title','')} at {e.get('company','')}"
            for e in resume_json.get("experience", [])[:4]
        )

        sections_template = ", ".join(
            f'"{s}": "3-4 sentences relevant to {job_title}"'
            for s in configured_sections
        )

        custom_prompt = f"""Generate compelling custom resume sections for this job opportunity.

Job: {job_title} at {job_company}
Skills needed: {job_skills}
Candidate: {candidate_name}
Experience: {experience_summary}

Generate 3-4 sentence content for each section showcasing relevant strengths:

Return ONLY valid JSON:
{{
  "sections": {{
    {sections_template}
  }}
}}

Each section: specific, substantial (3-4 sentences), aligned with job requirements."""

        custom_result = _call_ai(custom_prompt, temperature=0.1, max_tokens=4096)
        if "error" not in custom_result and custom_result.get("sections"):
            for name, content in custom_result["sections"].items():
                content_str = str(content).strip()
                if content_str and content_str != "null":
                    out["customSections"][name] = content_str

    return out


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
    return _call_ai(prompt, temperature=0.2)