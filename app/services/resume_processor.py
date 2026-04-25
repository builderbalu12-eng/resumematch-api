"""
Claude-powered resume / job processing logic.
SEPARATE from resume_generator.py (PDF only).
"""

import json
import logging
import base64
import io
from typing import Dict, Optional
import re

import pdfplumber

from app.config import settings

logger = logging.getLogger(__name__)


# Lazy import to avoid circular imports — used by call_ai() in ai_provider_service.
# Every prompt routes through call_ai → call_claude.
def _call_ai(prompt, temperature=1.0, max_tokens=8192, model=None):
    from app.services.ai_provider_service import call_ai
    return call_ai(prompt, temperature=temperature, max_tokens=max_tokens, model=model)


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

    # Log what we're actually sending to Claude
    logger.info(f"Input type: {'base64 PDF → extracted text' if is_base64_pdf else 'plain text'}")
    logger.info(f"Text length sent to Claude: {len(document_text)} chars")
    logger.info(f"First 400 chars:\n{document_text[:400]}...")

    # Step 2: Send clean text to Claude (Opus) for high-fidelity structured extraction.
    # Extraction quality matters: any section dropped here propagates to the tailor
    # output as a missing section. So we ask for every section the user might have
    # and use the strongest model + zero temperature.
    prompt = f"""You are a strict resume parser. Extract ONLY information LITERALLY present in the text below.
DO NOT invent, hallucinate, assume, or add information that is not in the text. Clean and normalize the text — fix missing spaces and obvious OCR artifacts — but never change meaning.
If a field is missing in the source → return null (for strings) or [] (for arrays) or {{}} (for objects).

Return ONLY this JSON — no markdown fences, no commentary:

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
  "projects": array of objects with keys: title, description, technologies (array of strings), link, date,
  "certifications": array of strings,
  "achievements": array of strings (top-level Achievements / Awards / Honors / Recognition section, NOT per-job bullets),
  "publications": array of strings (papers, articles, talks — include venue/journal where given),
  "hobbies": array of strings (interests, languages, volunteer activities short list),
  "customSections": object mapping any extra section header found in the resume (e.g. "Volunteering", "Languages", "Patents") to its body text — anything that doesn't fit the standard sections above
}}

Notes:
- "achievements" at the top level captures resume-wide awards (e.g. "Won Smart India Hackathon 2022"), separate from per-experience bullet metrics.
- "publications" captures research papers, book chapters, conference talks. Format each as a single string with title and venue.
- "customSections" is for headers you cannot map: e.g. "Patents", "Public Speaking", "Open Source", "Volunteering". Skip empty ones.

Raw resume text:
{document_text}
"""

    return _call_ai(prompt, temperature=0.0, max_tokens=8192, model="claude-opus-4-7")


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
    # B2 — Defensive guard: refuse to tailor if the input resume is empty/stub.
    # The frontend now always extracts pasted text via /api/extract-resume before
    # calling this endpoint, so a payload with no name + no experience + no skills
    # should never happen. If it does (older client, broken integration), bail
    # early instead of hallucinating from the JD.
    try:
        parsed_resume = json.loads(resume) if isinstance(resume, str) and resume.strip().startswith("{") else None
    except Exception:
        parsed_resume = None
    if isinstance(parsed_resume, dict):
        contact = parsed_resume.get("contact") or {}
        has_name = bool(str(contact.get("name", "")).strip()) and str(contact.get("name", "")).strip().lower() != "candidate"
        has_exp = bool(parsed_resume.get("experience"))
        has_skills = bool(parsed_resume.get("skills"))
        has_projects = bool(parsed_resume.get("projects"))
        has_edu = bool(parsed_resume.get("education"))
        if not (has_name or has_exp or has_skills or has_projects or has_edu):
            return {
                "error": "empty_resume",
                "message": "Resume payload is empty — extract structured data from the user's text first before calling tailor.",
            }

    prompt = f"""You are an expert ATS optimization specialist and professional resume writer.
Your goal is to tailor this resume for MAXIMUM ATS compatibility against the given job description.

## ABSOLUTE RULES — DO NOT VIOLATE
1. **STRICT SECTION PRESERVATION.** Return EXACTLY the sections the user gave you. Do NOT invent new sections. Do NOT merge sections. Do NOT move bullets between sections — a Project bullet must stay in `projects`, never under `experience`. An Education line must stay in `education`. Custom sections like "Volunteering" must stay in `customSections`.
2. **Section presence is faithful.** If the input resume has no Projects section, return `"projects": []`. If it has no Education, return `"education": []`. Do not fabricate sections to fill the JSON.
3. **Each section is enhanced individually** for ATS keyword density. Rewrite within a section, never across sections.
4. **No fabrication.** Keep all original facts — do not invent experience, employers, credentials, projects, or metrics.
5. **NEVER copy text from the Job Description into the resume output.** The JD is for keyword targeting only — it tells you which terms to weave into the user's existing content. It is NOT source material to fill missing sections. Specifically:
   - `education` MUST come from the user's actual education entries. If the JD says "B.E / B.Tech / Diploma / Master Degree, Instrumentation / Electronics / Computer Science / Information Science / MCA" and the user's real education is "BTech in Computer Science from Jawaharlal Nehru University", you return the USER'S entry, never the JD's qualification list.
   - `experience` MUST come from the user's actual jobs. If the user has zero experience entries, return `"experience": []` — do not synthesize a fake job from the JD's responsibilities.
   - `contact.name`, `contact.email`, `contact.phone`, `contact.location` MUST come from the user's resume. Never replace them with placeholders like "Candidate" or "John Doe".
   - Same rule for `projects`, `publications`, `achievements`, `certifications`, `hobbies`, `customSections`: source data is the USER's resume, not the JD.

## Step 1 — Extract ALL keywords from the job description
Identify every required skill, tool, technology, certification, and key phrase. Note exact terminology (e.g. "cross-functional collaboration", "CI/CD pipelines", "agile methodology") — ATS matches exact strings.

## Step 2 — Rewrite each section (only sections the user actually has)
- **contact**: pass through verbatim from the user's resume — name, email, phone, location, website, linkedin, github. Never modify.
- **summary**: 2–3 sentence professional summary emphasizing JD-relevant experience the user actually has. Do not invent skills.
- **skills**: reorder by descending JD relevance; keep all originals; you may add JD-priority skills only if the user demonstrably has them in their experience or projects.
- **experience**: rewrite bullets with JD keywords + exact JD phrasing; quantify only with numbers already in the original. Keep the original `title`, `company`, `startDate`, `endDate`, `location` exactly.
- **projects**: rewrite project descriptions to emphasize technologies/outcomes that match the JD. Each project keeps its title and any technologies the user listed.
- **education**: pass through the user's real education entries. Optionally surface a credential the user has if the JD mentions it.
- **certifications / achievements / publications / hobbies**: keep verbatim or lightly rephrase to add JD-relevant phrasing where honest.
- **customSections**: a free-form `Record<string, string>` map (e.g. {{"Volunteering": "...", "Languages": "..."}}). Preserve every key the user provided. Enhance the value text the same way as other sections.

## Step 3 — Per-section match score (drives the UI breakdown bars)
For each section the user has, compute a 0–100 match score = how strongly that section reflects the JD's keywords AFTER rewriting. Also count `jdKeywordsFound` (this section's matches against JD keyword list) and `jdKeywordsTotal` (total JD keywords). Skip sections the user does not have.

## Step 4 — Overall scores + diff
- `estimatedATSScore`: 0–100 overall ATS score AFTER tailoring.
- `originalAtsScore`: 0–100 estimated score for the ORIGINAL resume (before any rewrite).
- `keywordsAdded`: JD keywords newly surfaced by the rewrite (max 8).
- `keywordsPresent`: JD keywords already present in the original resume (max 8).
- `optimizationNotes`: 3–5 bullets describing the most impactful changes, each naming the section it touched.

## Output JSON — exact schema with realistic example values
Return ONLY valid JSON, no commentary, no markdown fences. Use EXACT original job titles, company names, project titles from the user's resume so they can be matched. Below is an example of what good output looks like — your output structure must match, but with the USER's real data:

{{
  "contact": {{
    "name": "Jane Doe",
    "email": "jane.doe@example.com",
    "phone": "+1-555-0100",
    "location": "Seattle, WA",
    "linkedin": "linkedin.com/in/janedoe"
  }},
  "summary": "Full-stack engineer with 4 years building React/Node.js platforms; led migration to TypeScript and shipped CI/CD pipelines processing 10M events/day.",
  "skills": ["TypeScript", "React", "Node.js", "PostgreSQL", "Docker", "GitHub Actions"],
  "experience": [
    {{
      "title": "Software Engineer II",
      "company": "Acme Corp",
      "location": "Remote",
      "startDate": "Jun 2022",
      "endDate": "Present",
      "isCurrentlyWorking": true,
      "description": [
        "Architected event-driven microservices in Node.js processing 10M+ events/day with 99.95% uptime.",
        "Migrated 80k LOC from JavaScript to TypeScript, reducing production type errors by 73%."
      ]
    }}
  ],
  "projects": [
    {{
      "title": "OpenScheduler",
      "description": "Open-source CRDT-based scheduling engine in TypeScript; 1.2k GitHub stars; used by 3 production teams.",
      "technologies": ["TypeScript", "WebSockets", "PostgreSQL"],
      "link": "github.com/janedoe/openscheduler"
    }}
  ],
  "education": [
    {{
      "institution": "University of Washington",
      "degree": "B.S.",
      "field": "Computer Science",
      "graduationDate": "Jun 2021",
      "gpa": "3.8"
    }}
  ],
  "certifications": ["AWS Certified Solutions Architect — Associate (2023)"],
  "achievements": ["Speaker, ReactConf 2024 — \\"Scaling CRDTs in production\\""],
  "publications": [],
  "hobbies": [],
  "customSections": {{}},
  "jobTitle": "Senior Frontend Engineer",
  "company": "TargetCo",
  "optimizationNotes": [
    "Summary: surfaced 'event-driven' and 'TypeScript migration' to mirror JD keywords.",
    "Skills: moved 'Docker' and 'GitHub Actions' to the front to match JD CI/CD focus.",
    "Experience: rewrote bullets to include 'microservices' and 'production' verbatim from the JD."
  ],
  "keywordsAdded": ["microservices", "event-driven", "CI/CD"],
  "keywordsPresent": ["TypeScript", "React", "Node.js", "PostgreSQL"],
  "sectionScores": [
    {{"section": "Summary",     "score": 78, "jdKeywordsFound": 5, "jdKeywordsTotal": 18}},
    {{"section": "Skills",      "score": 89, "jdKeywordsFound": 14, "jdKeywordsTotal": 18}},
    {{"section": "Experience",  "score": 72, "jdKeywordsFound": 11, "jdKeywordsTotal": 18}},
    {{"section": "Projects",    "score": 55, "jdKeywordsFound": 7, "jdKeywordsTotal": 18}},
    {{"section": "Education",   "score": 33, "jdKeywordsFound": 2, "jdKeywordsTotal": 18}}
  ],
  "estimatedATSScore": 84,
  "originalAtsScore": 56
}}

Reminder: only include sections the user actually has. Empty arrays / empty strings / empty objects for missing ones. Pass `contact` through verbatim from the user's input resume.

Original Resume (the source of truth — every field below comes from this):
{resume}

Job Description (used ONLY for keyword targeting — never copy text from here into the resume):
{job_description}
"""
    # B3 — strongest model + max tokens + zero temperature for accuracy.
    # Per user guidance: "use claude best for best resume optimisation, don't
    # hesitate to use Claude costs". Opus is ~5x Sonnet pricing but the user
    # explicitly approved this trade-off for resume tailoring quality.
    result = _call_ai(prompt, temperature=0.0, max_tokens=8192, model="claude-opus-4-7")

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
    Single combined Claude call: extract job data + tailor resume + ATS score.
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