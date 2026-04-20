import json
import asyncio
from datetime import datetime
from bson import ObjectId
from app.services.credits_service import CreditsService
from app.services.job_recommendation_service import (
    JobRecommendationService,
    _scrape_naukri_raw_sync,
    _scrape_jobspy_sync,
    _scrape_jsearch,
    _QuotaExhausted,
)
from app.config import settings
from app.services.lead_finder import LeadFinder
from app.services.resume_processor import tailor_resume as do_tailor_resume
from app.services.mongo import mongo
from app.models.chat.schemas import ChatMessage
from app.services.ai_provider_service import (
    call_ai,
    call_ai_text_async,
    call_ai_with_tools_async,
    send_tool_result_async,
)
from typing import List, Dict, Any, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Provider-agnostic tool manifest
# ─────────────────────────────────────────────────────────────────────────────

NOVA_TOOLS = [
    {
        "name": "search_jobs",
        "description": (
            "Search job boards for live openings matching a specific role and location. "
            "Call this when the user wants to find job listings. "
            "Only call when you have a real job title and city — never pass vague terms."
        ),
        "parameters": {
            "role":     {"type": "string", "description": "Exact job title (e.g. 'software engineer', 'data analyst', 'product manager')"},
            "location": {"type": "string", "description": "City or region (e.g. 'bangalore', 'mumbai', 'delhi', 'india')"},
        },
        "required": ["role", "location"],
    },
    {
        "name": "save_job_preferences",
        "description": "Save the user's target job role and preferred location to their profile so future searches use them automatically.",
        "parameters": {
            "desired_role":       {"type": "string", "description": "Job title the user is targeting"},
            "preferred_location": {"type": "string", "description": "Preferred city or location"},
        },
        "required": ["desired_role", "preferred_location"],
    },
    {
        "name": "tailor_resume",
        "description": "ATS-optimize the user's uploaded resume for a specific job description. Requires the full job description text.",
        "parameters": {
            "job_description": {"type": "string", "description": "Full job description text to tailor the resume for"},
        },
        "required": ["job_description"],
    },
    {
        "name": "evaluate_job",
        "description": "Score a job posting against the user's resume and career goals. Returns a grade, score, and axis breakdown.",
        "parameters": {
            "job_description": {"type": "string", "description": "Full job description text to evaluate"},
        },
        "required": ["job_description"],
    },
    {
        "name": "research_company",
        "description": "Research a company to help the user prepare for an interview or decide whether to apply.",
        "parameters": {
            "company_name": {"type": "string", "description": "Exact company name to research"},
        },
        "required": ["company_name"],
    },
    {
        "name": "generate_followup_email",
        "description": "Write a professional follow-up email + LinkedIn message for a submitted job application.",
        "parameters": {
            "company": {"type": "string", "description": "Company name (leave blank to use the most recent tracked application)"},
        },
        "required": [],
    },
    {
        "name": "generate_outreach_message",
        "description": "Write a personalised LinkedIn connection message for a hiring contact or recruiter.",
        "parameters": {
            "context": {"type": "string", "description": "Who to contact and why (e.g. 'hiring manager at Google for senior engineer role')"},
        },
        "required": ["context"],
    },
    {
        "name": "find_business_leads",
        "description": "Find local business leads via Google Maps for sales prospecting. Supports ANY business type or category.",
        "parameters": {
            "city":      {"type": "string", "description": "City to search in (e.g. 'bangalore', 'mumbai', 'delhi')"},
            "category":  {"type": "string", "description": "Any business type (e.g. 'gym', 'yoga studio', 'coffee shop', 'software company', 'dental clinic', 'bakery', 'clothing store')"},
            "radius_km": {"type": "number", "description": "Search radius in km (default 5)"},
        },
        "required": ["city", "category"],
    },
    {
        "name": "analyze_lead",
        "description": (
            "Analyze a specific business lead: what services they likely need, "
            "competitor context, review sentiment, and a one-line outreach pitch. "
            "Call when the user asks to analyze or learn more about a specific business lead."
        ),
        "parameters": {
            "name":        {"type": "string", "description": "Business name"},
            "address":     {"type": "string", "description": "Business address"},
            "category":    {"type": "string", "description": "Business category"},
            "rating":      {"type": "number", "description": "Google Maps rating (0 if unknown)"},
            "has_website": {"type": "boolean", "description": "Whether the business has a real website"},
            "city":        {"type": "string", "description": "City the business is in"},
        },
        "required": ["name", "category"],
    },
    {
        "name": "save_portfolio_url",
        "description": (
            "Save or update the user's portfolio, personal website, LinkedIn, or GitHub URL. "
            "Call whenever the user shares or mentions any personal URL, portfolio site, LinkedIn profile, or GitHub link."
        ),
        "parameters": {
            "url":      {"type": "string", "description": "The full URL including https://"},
            "url_type": {"type": "string", "description": "One of: portfolio, linkedin, github, other"},
        },
        "required": ["url", "url_type"],
    },
    {
        "name": "find_freelancers",
        "description": (
            "Search platform users who are available for hire as freelancers. "
            "ALWAYS collect: (a) what skill/work type is needed AND (b) max budget (or user says 'any budget'). "
            "Never call without at least a skill."
        ),
        "parameters": {
            "skill":      {"type": "string", "description": "Skill or type of work needed (e.g. 'React developer', 'logo design', 'copywriting')"},
            "location":   {"type": "string", "description": "Preferred location or '' for remote/any"},
            "budget_max": {"type": "number", "description": "Max hourly rate in USD. Use 0 if user says 'any budget' or flexible."},
        },
        "required": ["skill", "budget_max"],
    },
    {
        "name": "update_master_resume",
        "description": (
            "Replace the user's master resume with newly provided resume text from a file they uploaded in chat. "
            "ONLY call AFTER the user has explicitly confirmed they want to replace their existing resume."
        ),
        "parameters": {
            "resume_text": {"type": "string", "description": "Full extracted resume text from the uploaded file"},
        },
        "required": ["resume_text"],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Resume helper
# ─────────────────────────────────────────────────────────────────────────────

def _build_tailored_text(result: dict) -> str:
    lines = []
    if result.get("summary"):
        lines += ["## Summary", result["summary"], ""]
    if result.get("skills"):
        lines += ["## Skills", ", ".join(result["skills"]), ""]
    for exp in result.get("experience", []):
        lines.append(f"## {exp.get('title')} at {exp.get('company')}")
        for b in exp.get("description", []):
            lines.append(f"- {b}")
        lines.append("")
    for proj in result.get("projects", []):
        lines += [f"## {proj.get('title')}", proj.get("description", ""), ""]
    return "\n".join(lines)


def _merge_tailored_resume(result: dict, orig: dict) -> dict:
    orig_exp_map = {
        (e.get("title", "").lower(), e.get("company", "").lower()): e
        for e in orig.get("experience", [])
    }
    merged_exp = []
    for te in result.get("experience", []):
        key = (te.get("title", "").lower(), te.get("company", "").lower())
        oe  = orig_exp_map.get(key, {})
        merged_exp.append({
            "title":              te.get("title", oe.get("title", "")),
            "company":            te.get("company", oe.get("company", "")),
            "location":           oe.get("location"),
            "startDate":          oe.get("startDate", ""),
            "endDate":            oe.get("endDate"),
            "isCurrentlyWorking": oe.get("isCurrentlyWorking", False),
            "description":        te.get("description", []),
        })

    orig_proj_map = {p.get("title", "").lower(): p for p in orig.get("projects", [])}
    merged_proj = []
    for tp in result.get("projects", []):
        op = orig_proj_map.get(tp.get("title", "").lower(), {})
        merged_proj.append({
            "title":        tp.get("title", ""),
            "description":  tp.get("description", ""),
            "technologies": op.get("technologies", []),
            "link":         op.get("link"),
            "date":         op.get("date"),
        })

    return {
        "contact":        orig.get("contact", {}),
        "summary":        result.get("summary", ""),
        "skills":         result.get("skills", []),
        "experience":     merged_exp,
        "education":      orig.get("education", []),
        "projects":       merged_proj,
        "certifications": orig.get("certifications", []),
    }


async def _get_user_resume_text(user_id: str) -> str:
    """Fetch and flatten the user's latest resume from incoming_resumes."""
    doc = await mongo.incoming_resumes.find_one(
        {"user_id": user_id},
        sort=[("created_at", -1)],
    )
    if not doc:
        raise ValueError("no_resume")

    extracted = doc.get("extracted_data")
    if extracted and isinstance(extracted, dict):
        parts = []
        for key, val in extracted.items():
            if val:
                if isinstance(val, list):
                    parts.append(f"{key}: {', '.join(str(v) for v in val)}")
                elif isinstance(val, dict):
                    parts.append(f"{key}: {json.dumps(val)}")
                else:
                    parts.append(f"{key}: {val}")
        if parts:
            return "\n".join(parts)

    return doc.get("raw_text") or doc.get("text") or ""


async def _get_user_resume_text_safe(user_id: str) -> str:
    try:
        return await _get_user_resume_text(user_id)
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# System prompt builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_system_prompt(user_doc: dict, resume_text: str) -> str:
    prefs             = user_doc.get("jobPreferences") or user_doc.get("job_preferences") or {}
    desired_role      = prefs.get("desired_role") or prefs.get("desiredRole") or "not set"
    preferred_location = prefs.get("preferred_location") or prefs.get("preferredLocation") or "not set"
    north_star        = (user_doc.get("northStar") or "not set").strip()
    first_name        = user_doc.get("firstName", "")
    prefs_collected   = bool(prefs.get("desired_role") or prefs.get("desiredRole"))

    resume_status  = "loaded" if resume_text else "not uploaded"
    resume_snippet = resume_text[:1500] if resume_text else ""

    return f"""You are Nova, an AI career and business assistant. You help users find jobs, improve resumes, research companies, and find business leads.

## User Context
- Name: {first_name or "unknown"}
- Resume: {resume_status}
- Resume summary: {resume_snippet if resume_snippet else "N/A"}
- Target role: {desired_role}
- Preferred location: {preferred_location}
- Career goal: {north_star}
- Job preferences previously saved: {prefs_collected}

## How to respond
1. **Job search**: If the user wants jobs AND you know their target role + location (from context or message), call `search_jobs` immediately. If both are unknown and never saved, ask naturally — then on next message call `save_job_preferences` and `search_jobs`.
2. **Resume tailoring**: You need the full job description. If not provided, ask the user to paste it first.
3. **Precision**: Never pass vague terms like "matching my profile" to `search_jobs`. Always use a concrete job title and city.
4. **Tone**: Respond in lowercase, conversational, like a sharp career coach. Direct, warm, and brief.
5. **Domain**: Help with careers, jobs, resumes, business leads, freelancer search, and professional development. Politely decline anything unrelated.
6. **General chat**: If the user says hi, asks career questions, or wants advice — respond naturally without calling any tool.
7. **Portfolio / links**: If the user shares or mentions any URL (portfolio, LinkedIn, GitHub, personal site) — immediately call `save_portfolio_url`. Don't ask, just save it and confirm.
8. **Freelancer search**: Before calling `find_freelancers`, ask for (a) what skill/work type they need and (b) their budget. Then call.
9. **Resume file upload**: If a message starts with `__RESUME_FILE__` the user has attached a resume file. First reply: "i can see you've uploaded a resume — this will replace your current master resume. shall i go ahead?". Wait for confirmation ("yes"/"go ahead"/similar) then call `update_master_resume` with the resume text (everything after `__RESUME_FILE__\n`). If they say no, drop it.
10. **Lead analysis**: If the message starts with `analyze lead:` — call `analyze_lead` immediately. Parse the pipe-separated string for name, address, rating, category, has_website, city."""


# ─────────────────────────────────────────────────────────────────────────────
# Service class
# ─────────────────────────────────────────────────────────────────────────────

class AIChatService:

    def __init__(self):
        self.job_service = JobRecommendationService()
        self.lead_finder = LeadFinder()

    async def process_message(
        self,
        user_id: str,
        message: str,
        session_history: List[ChatMessage],
    ) -> Dict[str, Any]:
        try:
            user_doc = await mongo.users.find_one({"_id": ObjectId(user_id)})
            if not user_doc:
                return {
                    "response": "user not found.",
                    "intent": "error",
                    "action_type": None,
                    "action_data": None,
                    "success": False,
                }

            resume_text = await _get_user_resume_text_safe(user_id)
            system      = _build_system_prompt(user_doc, resume_text)

            # Convert session history to provider-agnostic format
            history = []
            for msg in session_history[-10:]:
                role = "user" if msg.role.value == "user" else "assistant"
                history.append({"role": role, "content": msg.content})

            # Ask the AI (with tools)
            result = await call_ai_with_tools_async(system, history, message, NOVA_TOOLS)

            # ── Text response (no tool called) ────────────────────────────
            if result["type"] == "text":
                if (result.get("input_tokens") or 0) > 0:
                    await CreditsService.log_deduction(
                        user_id=user_id, amount=0, feature="ai_chat",
                        function_name="nova_chat",
                        description="Nova conversation turn",
                        input_tokens=result.get("input_tokens", 0),
                        output_tokens=result.get("output_tokens", 0),
                    )
                return {
                    "response":    result["text"],
                    "intent":      "general_chat",
                    "action_type": None,
                    "action_data": None,
                    "success":     True,
                }

            # ── Tool call ─────────────────────────────────────────────────
            tool_name = result["tool_name"]
            tool_args = result["tool_args"]

            tool_result = await self._execute_tool(tool_name, tool_args, user_id)

            # Ask AI to turn tool result into a natural reply
            final_text = await send_tool_result_async(
                system_prompt=system,
                history=history,
                message=message,
                first_response_raw=result["raw_response"],
                tool_name=tool_name,
                tool_result_summary=tool_result.get("summary", tool_result.get("response", "")),
                provider_state=result.get("provider_state", {}),
                tools=NOVA_TOOLS,
            )

            if (result.get("input_tokens") or 0) > 0:
                await CreditsService.log_deduction(
                    user_id=user_id, amount=0, feature="ai_chat",
                    function_name="nova_tool_call",
                    description=f"Nova tool: {tool_name}",
                    input_tokens=result.get("input_tokens", 0),
                    output_tokens=result.get("output_tokens", 0),
                )

            return {
                "response":    final_text or tool_result.get("response", "done."),
                "intent":      tool_name,
                "action_type": tool_result.get("action_type"),
                "action_data": tool_result.get("action_data"),
                "success":     True,
            }

        except Exception as e:
            print(f"AI Chat Service error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "response":    "i'm having trouble right now. please try again in a moment.",
                "intent":      "error",
                "action_type": None,
                "action_data": None,
                "success":     False,
            }

    # ── Streaming message processor ────────────────────────────────────────

    async def process_message_stream(
        self,
        user_id: str,
        message: str,
        session_history: List[ChatMessage],
    ):
        """Async generator that yields SSE-ready dicts for streaming responses."""
        timestamp = datetime.utcnow().isoformat()
        try:
            user_doc = await mongo.users.find_one({"_id": ObjectId(user_id)})
            if not user_doc:
                yield {"type": "done", "response": "user not found.", "intent": "error",
                       "action_type": None, "action_data": None, "timestamp": timestamp}
                return

            resume_text = await _get_user_resume_text_safe(user_id)
            system      = _build_system_prompt(user_doc, resume_text)
            history = []
            for msg in session_history[-10:]:
                role = "user" if msg.role.value == "user" else "assistant"
                history.append({"role": role, "content": msg.content})

            result = await call_ai_with_tools_async(system, history, message, NOVA_TOOLS)

            if result["type"] == "text":
                yield {"type": "done", "response": result["text"], "intent": "general_chat",
                       "action_type": None, "action_data": None, "timestamp": timestamp}
                return

            tool_name = result["tool_name"]
            tool_args = result["tool_args"]

            # ── Leads: true per-lead streaming ─────────────────────────────
            if tool_name == "find_business_leads":
                city       = tool_args.get("city", "bangalore")
                category   = tool_args.get("category", "business")
                radius_km  = float(tool_args.get("radius_km", 5.0))

                cost = await CreditsService.get_feature_cost("find_leads")
                if cost > 0:
                    user_d  = await mongo.users.find_one({"_id": ObjectId(user_id)})
                    balance = float(user_d.get("credits", 0)) if user_d else 0.0
                    if balance < cost:
                        yield {"type": "done",
                               "response": f"you don't have enough credits (need {cost:.0f}, have {balance:.0f}). visit /pricing to top up.",
                               "intent": tool_name, "action_type": None, "action_data": None, "timestamp": timestamp}
                        return
                    scraper_limit = min(20, int(balance // cost))
                else:
                    scraper_limit = 20

                count = 0
                async for lead_doc in self.lead_finder.find_and_stream_leads(
                    city=city, category=category, radius_km=radius_km,
                    owner_id=user_id, mongo=mongo, limit=scraper_limit,
                ):
                    count += 1
                    yield {
                        "type":        "item",
                        "action_type": "leads_results",
                        "item": {
                            "Name":        lead_doc.get("name", ""),
                            "Phone":       lead_doc.get("phone", ""),
                            "Address":     lead_doc.get("address", ""),
                            "Website":     lead_doc.get("website") or "",
                            "Has Website": bool(lead_doc.get("has_website")),
                            "Rating":      lead_doc.get("rating"),
                            "Category":    lead_doc.get("category", category),
                            "lat":         lead_doc.get("lat"),
                            "lng":         lead_doc.get("lng"),
                        },
                        "meta": {"city": city, "category": category},
                    }

                if count == 0:
                    yield {"type": "done",
                           "response": f"couldn't find any {category} leads in {city}. try a different city or category.",
                           "intent": tool_name, "action_type": None, "action_data": None, "timestamp": timestamp}
                    return

                if cost > 0:
                    await CreditsService.deduct_credits(user_id, amount=cost * count, feature="find_leads")

                yield {"type": "done",
                       "response": f"found **{count} leads** in {city.title()} ({category}). download the spreadsheet below.",
                       "intent": tool_name, "action_type": None,
                       "action_data": {"count": count, "city": city, "category": category},
                       "timestamp": timestamp}

            # ── Jobs: fetch all → stream cards individually ────────────────
            elif tool_name == "search_jobs":
                tool_result = await self._execute_tool(tool_name, tool_args, user_id)
                jobs = (tool_result.get("action_data") or {}).get("jobs", [])
                for job in jobs:
                    yield {"type": "item", "action_type": "jobs_results", "item": job}
                yield {"type": "done",
                       "response": tool_result.get("response", f"found {len(jobs)} jobs."),
                       "intent": tool_name, "action_type": None,
                       "action_data": {"count": len(jobs)}, "timestamp": timestamp}

            # ── Freelancers: fetch all → stream cards individually ─────────
            elif tool_name == "find_freelancers":
                tool_result = await self._execute_tool(tool_name, tool_args, user_id)
                freelancers = (tool_result.get("action_data") or {}).get("freelancers", [])
                for f in freelancers:
                    yield {"type": "item", "action_type": "freelancers_results", "item": f}
                yield {"type": "done",
                       "response": tool_result.get("response", f"found {len(freelancers)} freelancers."),
                       "intent": tool_name, "action_type": None,
                       "action_data": {"count": len(freelancers), "skill": tool_args.get("skill", "")},
                       "timestamp": timestamp}

            # ── Tailor resume: progress events then done ──────────────────
            elif tool_name == "tailor_resume":
                job_description = tool_args.get("job_description", "")

                yield {"type": "progress", "action_type": "tailored_resume",
                       "step": 1, "total_steps": 3,
                       "step_label": "Analyzing job description keywords…"}

                try:
                    resume_text = await _get_user_resume_text(user_id)
                except ValueError:
                    yield {"type": "done",
                           "response": "you haven't uploaded a resume yet. go to **[/upload](/upload)** first.",
                           "intent": tool_name, "action_type": None, "action_data": None,
                           "timestamp": timestamp}
                    return

                if not resume_text.strip():
                    yield {"type": "done",
                           "response": "your resume appears to be empty. please re-upload at **[/upload](/upload)**.",
                           "intent": tool_name, "action_type": None, "action_data": None,
                           "timestamp": timestamp}
                    return

                cost = await CreditsService.get_feature_cost("tailor_resume")
                if cost > 0:
                    ok, msg = await CreditsService.deduct_credits(user_id, amount=cost, feature="tailor_resume")
                    if not ok:
                        yield {"type": "done",
                               "response": f"not enough credits to tailor your resume. {msg}\n\nvisit /pricing to top up.",
                               "intent": tool_name, "action_type": None, "action_data": None,
                               "timestamp": timestamp}
                        return

                yield {"type": "progress", "action_type": "tailored_resume",
                       "step": 2, "total_steps": 3,
                       "step_label": "Tailoring resume for maximum ATS compatibility…"}

                loop   = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, lambda: do_tailor_resume(resume_text, job_description)
                )

                yield {"type": "progress", "action_type": "tailored_resume",
                       "step": 3, "total_steps": 3,
                       "step_label": "Computing ATS score and generating insights…"}

                ats_score   = result.get("estimatedATSScore", 0)
                notes       = result.get("optimizationNotes", [])
                notes_md    = "\n".join(f"- {n}" for n in notes[:6])
                orig_struct = await self._get_user_resume_structured(user_id)
                tailored    = _build_tailored_text(result)
                resume_data = _merge_tailored_resume(result, orig_struct)
                score_bd    = result.get("scoreBreakdown", {})

                yield {"type": "done",
                       "response": f"resume tailored! estimated ATS score: **{ats_score}%**\n\n**key improvements:**\n{notes_md}\n\ndownload your tailored resume below.",
                       "intent": tool_name,
                       "action_type": "tailored_resume",
                       "action_data": {
                           "tailored_resume":    tailored,
                           "resume_data":        resume_data,
                           "ats_score":          ats_score,
                           "score_breakdown":    score_bd,
                           "optimization_notes": notes,
                           "job_title":          result.get("jobTitle", ""),
                           "company":            result.get("company", ""),
                       },
                       "timestamp": timestamp}

            # ── All other tools: run normally, single done event ───────────
            else:
                tool_result = await self._execute_tool(tool_name, tool_args, user_id)
                final_text  = await send_tool_result_async(
                    system_prompt=system, history=history, message=message,
                    first_response_raw=result["raw_response"], tool_name=tool_name,
                    tool_result_summary=tool_result.get("summary", tool_result.get("response", "")),
                    provider_state=result.get("provider_state", {}), tools=NOVA_TOOLS,
                )
                yield {"type": "done",
                       "response":    final_text or tool_result.get("response", "done."),
                       "intent":      tool_name,
                       "action_type": tool_result.get("action_type"),
                       "action_data": tool_result.get("action_data"),
                       "timestamp":   timestamp}

        except Exception as e:
            print(f"process_message_stream error: {e}")
            import traceback; traceback.print_exc()
            yield {"type": "done", "response": "i'm having trouble right now. please try again.",
                   "intent": "error", "action_type": None, "action_data": None, "timestamp": timestamp}

    # ── Tool dispatcher ────────────────────────────────────────────────────

    async def _execute_tool(self, tool_name: str, tool_args: dict, user_id: str) -> dict:
        try:
            dispatch = {
                "search_jobs":             lambda: self._handle_find_jobs(
                    role=tool_args.get("role", "software engineer"),
                    location=tool_args.get("location", "india"),
                    user_id=user_id,
                ),
                "save_job_preferences":    lambda: self._handle_save_preferences(
                    desired_role=tool_args.get("desired_role", ""),
                    preferred_location=tool_args.get("preferred_location", ""),
                    user_id=user_id,
                ),
                "tailor_resume":           lambda: self._handle_tailor_resume(
                    job_description=tool_args.get("job_description", ""),
                    user_id=user_id,
                ),
                "evaluate_job":            lambda: self._handle_evaluate_job(
                    job_description=tool_args.get("job_description", ""),
                    user_id=user_id,
                ),
                "research_company":        lambda: self._handle_company_research(
                    company_name=tool_args.get("company_name", ""),
                    user_id=user_id,
                ),
                "generate_followup_email": lambda: self._handle_generate_followup(
                    company=tool_args.get("company", ""),
                    user_id=user_id,
                ),
                "generate_outreach_message": lambda: self._handle_generate_outreach(
                    context=tool_args.get("context", ""),
                    user_id=user_id,
                ),
                "find_business_leads":     lambda: self._handle_find_leads(
                    city=tool_args.get("city", "bangalore"),
                    category=tool_args.get("category", "business"),
                    radius_km=float(tool_args.get("radius_km", 5.0)),
                    user_id=user_id,
                ),
                "save_portfolio_url":      lambda: self._handle_save_portfolio_url(
                    url=tool_args.get("url", ""),
                    url_type=tool_args.get("url_type", "portfolio"),
                    user_id=user_id,
                ),
                "find_freelancers":        lambda: self._handle_find_freelancers(
                    skill=tool_args.get("skill", ""),
                    location=tool_args.get("location", ""),
                    budget_max=float(tool_args.get("budget_max", 0)),
                    user_id=user_id,
                ),
                "update_master_resume":    lambda: self._handle_update_master_resume(
                    resume_text=tool_args.get("resume_text", ""),
                    user_id=user_id,
                ),
                "analyze_lead":            lambda: self._handle_analyze_lead(
                    name=tool_args.get("name", ""),
                    address=tool_args.get("address", ""),
                    category=tool_args.get("category", ""),
                    rating=float(tool_args.get("rating", 0)),
                    has_website=bool(tool_args.get("has_website", False)),
                    city=tool_args.get("city", ""),
                    user_id=user_id,
                ),
            }

            handler = dispatch.get(tool_name)
            if handler:
                response, action_data, action_type = await handler()
            else:
                response, action_data, action_type = f"unknown tool: {tool_name}", None, None

            # Build a concise machine-readable summary for the AI round-trip
            summary = response
            if action_data:
                if "jobs" in action_data:
                    jobs = action_data["jobs"]
                    summary = (
                        f"Found {len(jobs)} job listings: "
                        + ", ".join(f"{j['Title']} at {j['Company']} ({j['Location']})" for j in jobs[:3])
                    )
                elif "leads" in action_data:
                    summary = (
                        f"Found {action_data.get('count', 0)} business leads in "
                        f"{action_data.get('city', '')} ({action_data.get('category', '')})."
                    )
                elif "tailored_resume" in action_data:
                    summary = f"Resume tailored. ATS score: {action_data.get('ats_score', '?')}%."
                elif "grade" in action_data:
                    summary = f"Job scored {action_data['grade']} ({action_data.get('score', '?')}/5). {action_data.get('verdict', '')}."
                elif "freelancers" in action_data:
                    fl = action_data["freelancers"]
                    summary = f"Found {len(fl)} freelancer(s) for '{action_data.get('skill', '')}': " + ", ".join(f["name"] for f in fl[:3])

            return {
                "response":    response,
                "action_type": action_type,
                "action_data": action_data,
                "summary":     summary,
            }

        except Exception as e:
            print(f"Tool execution error [{tool_name}]: {e}")
            return {
                "response":    "i ran into an issue. please try again.",
                "action_type": None,
                "action_data": None,
                "summary":     "Tool execution failed.",
            }

    # ── Find jobs ──────────────────────────────────────────────────────────

    async def _handle_find_jobs(
        self, role: str, location: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            cost = await CreditsService.get_feature_cost("find_jobs")

            user_doc = await mongo.users.find_one({"_id": ObjectId(user_id)})
            if not user_doc:
                return ("user not found.", None, None)

            if cost > 0:
                balance = float(user_doc.get("credits", 0))
                if balance < cost:
                    return (
                        f"you don't have enough credits to search for jobs (need {cost:.0f}, you have {balance:.0f}). visit /pricing to top up.",
                        None, None,
                    )

            search_term = role.strip() or "software engineer"
            loc = location.lower().strip() or "india"
            if "bengaluru" in loc:
                loc = "bangalore"

            loop = asyncio.get_event_loop()
            raw_results: List[Dict] = []

            # 1. JSearch (RapidAPI) — most reliable, async
            if not raw_results:
                try:
                    raw_results = await _scrape_jsearch(
                        search_term=search_term,
                        location=loc,
                        hours_old=72,
                        is_remote=None,
                        api_key=settings.jsearch_api_key,
                    )
                except (_QuotaExhausted, Exception) as e:
                    print(f"[Jobs] JSearch failed: {e}")

            # 2. Naukri raw scraper
            if not raw_results:
                raw_results = await loop.run_in_executor(
                    None,
                    lambda: _scrape_naukri_raw_sync(search_term, loc, pages=2),
                )

            # 3. JobSpy (LinkedIn + Indeed)
            if not raw_results:
                raw_results = await loop.run_in_executor(
                    None,
                    lambda: _scrape_jobspy_sync(
                        search_term=search_term,
                        location=loc,
                        results_per_site=5,
                        hours_old=72,
                        sites=["linkedin", "indeed"],
                        country_indeed="india",
                        is_remote=None,
                        proxies=None,
                    ),
                )

            # 4. Retry JSearch with broad "india" location
            if not raw_results and loc != "india":
                try:
                    raw_results = await _scrape_jsearch(
                        search_term=search_term,
                        location="india",
                        hours_old=168,
                        is_remote=None,
                        api_key=settings.jsearch_api_key,
                    )
                    if raw_results:
                        loc = "india"
                except (_QuotaExhausted, Exception):
                    pass

            # 5. Absolute fallback — broader role keyword search across india
            if not raw_results:
                broad_term = search_term.split()[0] if search_term else "developer"
                try:
                    raw_results = await _scrape_jsearch(
                        search_term=broad_term,
                        location="india",
                        hours_old=336,
                        is_remote=None,
                        api_key=settings.jsearch_api_key,
                    )
                    if raw_results:
                        search_term = broad_term
                        loc = "india"
                except (_QuotaExhausted, Exception):
                    pass

            if not raw_results:
                return (
                    f"i couldn't pull live listings right now for **{search_term}** in **{loc}** — the job boards seem to be blocking scrapers at the moment.\n\n"
                    f"here's what you can do:\n"
                    f"- try the **[/findjob](/findjob)** page for broader search options\n"
                    f"- search on [Naukri](https://www.naukri.com/jobs-in-{loc.replace(' ', '-')}?k={search_term.replace(' ', '+')}) directly\n"
                    f"- search on [LinkedIn](https://www.linkedin.com/jobs/search/?keywords={search_term.replace(' ', '+')}&location={loc}) directly\n\n"
                    f"no credits were deducted.",
                    None, None,
                )

            top_results = raw_results[:5]

            if cost > 0:
                total_cost = cost * len(top_results)
                ok, deduct_msg = await CreditsService.deduct_credits(user_id, amount=total_cost, feature="find_jobs")
                if not ok:
                    return (f"credit deduction failed. {deduct_msg}\n\nvisit /pricing to top up.", None, None)
            jobs_base = [
                {
                    "Title":      j.get("title", ""),
                    "Company":    j.get("company", ""),
                    "Location":   j.get("location", ""),
                    "Experience": j.get("experience", ""),
                    "Salary":     j.get("salary", ""),
                    "Site":       j.get("site", ""),
                    "Type":       j.get("job_type", ""),
                    "URL":        j.get("job_url", ""),
                }
                for j in top_results
            ]

            # Generate per-job pitch using the active AI provider
            try:
                pitch_prompt = (
                    f"write brief 1-2 sentence lowercase conversational pitches for a job seeker targeting: {search_term}.\n"
                    f"for each job below, explain why it's a great fit. output ONLY a JSON array of strings — no markdown, no extra text.\n\n"
                    + "\n".join(
                        f"{i+1}. {j['Title']} at {j['Company']} ({j['Location']})"
                        for i, j in enumerate(jobs_base)
                    )
                )
                raw_text = await call_ai_text_async(pitch_prompt, temperature=0.5, max_tokens=800)
                raw_text = raw_text.strip()
                if raw_text.startswith("```"):
                    lines    = raw_text.split("\n")
                    end      = -1 if lines[-1].strip().startswith("```") else len(lines)
                    raw_text = "\n".join(lines[1:end])
                pitches = json.loads(raw_text)
                for i, job in enumerate(jobs_base):
                    job["pitch"] = pitches[i] if i < len(pitches) else ""
            except Exception as pe:
                print(f"Pitch generation failed: {pe}")
                for job in jobs_base:
                    job.setdefault("pitch", "")

            return (
                f"here are the top **{len(jobs_base)} {search_term} roles** i found in {loc.title()} ✨",
                {"jobs": jobs_base, "count": len(jobs_base)},
                "jobs_results",
            )

        except Exception as e:
            print(f"find_jobs handler error: {e}")
            return ("i'm having trouble searching for jobs right now. please try again.", None, None)

    # ── Save preferences ───────────────────────────────────────────────────

    async def _handle_save_preferences(
        self, desired_role: str, preferred_location: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            await mongo.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {
                    "jobPreferences.desired_role":       desired_role,
                    "jobPreferences.preferred_location": preferred_location,
                    "jobPreferences.updated_at":         datetime.utcnow(),
                }},
            )
            return (
                f"saved your preferences: {desired_role} in {preferred_location}.",
                None, None,
            )
        except Exception as e:
            print(f"save_preferences error: {e}")
            return ("couldn't save your preferences. please try again.", None, None)

    # ── Find business leads (Google Maps) ─────────────────────────────────

    async def _handle_find_leads(
        self, city: str, category: str, radius_km: float, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            cost = await CreditsService.get_feature_cost("find_leads")

            if cost > 0:
                user_doc = await mongo.users.find_one({"_id": ObjectId(user_id)})
                balance  = float(user_doc.get("credits", 0)) if user_doc else 0.0
                max_affordable = int(balance // cost)
                if max_affordable == 0:
                    return (
                        f"you don't have enough credits to find leads (need at least {cost:.0f}, you have {balance:.0f}). visit /pricing to top up.",
                        None, None,
                    )
                scraper_limit = min(20, max_affordable)
            else:
                scraper_limit = 20

            raw_leads = await self.lead_finder.find_and_save_leads(
                city=city,
                category=category,
                radius_km=radius_km,
                owner_id=user_id,
                mongo=mongo,
                limit=scraper_limit,
            )

            if not raw_leads:
                return (
                    f"i couldn't find any {category} leads in {city}. try a different city or category.",
                    None, None,
                )

            if cost > 0:
                total_cost = cost * len(raw_leads)
                ok, msg = await CreditsService.deduct_credits(user_id, amount=total_cost, feature="find_leads")
                if not ok:
                    return (f"credit deduction failed after finding leads. {msg}\n\nvisit /pricing to top up.", None, None)

            leads = [
                {
                    "Name":        l.get("name", ""),
                    "Phone":       l.get("phone", ""),
                    "Address":     l.get("address", ""),
                    "Website":     l.get("website") or "",
                    "Has Website": bool(l.get("has_website")),
                    "Rating":      l.get("rating"),
                    "Category":    l.get("category", category),
                    "lat":         l.get("lat"),
                    "lng":         l.get("lng"),
                }
                for l in raw_leads
            ]
            return (
                f"found **{len(leads)} leads** in {city.title()} ({category}). download the spreadsheet below.",
                {"leads": leads, "count": len(leads), "city": city, "category": category},
                "leads_results",
            )

        except Exception as e:
            print(f"find_leads handler error: {e}")
            return ("i'm having trouble finding leads right now. please try again.", None, None)

    # ── Analyze lead ───────────────────────────────────────────────────────

    async def _handle_analyze_lead(
        self, name: str, address: str, category: str,
        rating: float, has_website: bool, city: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            cost = await CreditsService.get_feature_cost("lead_analyze")
            if cost > 0:
                ok, msg = await CreditsService.deduct_credits(user_id, amount=cost, feature="lead_analyze")
                if not ok:
                    return (f"you need credits to analyze leads. {msg}\n\nvisit /pricing to top up.", None, None)

            website_str = "yes" if has_website else "no"
            rating_str  = f"{rating}/5" if rating else "unknown"
            prompt = (
                f"You are a B2B sales consultant helping identify opportunities.\n\n"
                f"Business: {name}\n"
                f"Category: {category}\n"
                f"City: {city or 'unknown'}\n"
                f"Address: {address or 'not provided'}\n"
                f"Google Maps rating: {rating_str}\n"
                f"Has website: {website_str}\n\n"
                f"In 3-4 concise sentences covering:\n"
                f"1. What digital or marketing services this business most likely needs right now\n"
                f"2. How they compare to typical competitors in their sector\n"
                f"3. A single punchy cold outreach opening line you would use\n\n"
                f"Be direct. No bullet points. Plain prose."
            )
            analysis = await call_ai_text_async(prompt, temperature=0.6, max_tokens=250)
            return (analysis.strip(), None, None)
        except Exception as e:
            print(f"analyze_lead handler error: {e}")
            return ("couldn't generate analysis right now. please try again.", None, None)

    # ── Resume structured data ────────────────────────────────────────────

    async def _get_user_resume_structured(self, user_id: str) -> dict:
        doc = await mongo.incoming_resumes.find_one(
            {"user_id": user_id}, sort=[("created_at", -1)]
        )
        return (doc or {}).get("extracted_data") or {}

    # ── Tailor resume ──────────────────────────────────────────────────────

    async def _handle_tailor_resume(
        self, job_description: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        cost = 0.0
        try:
            try:
                resume_text = await _get_user_resume_text(user_id)
            except ValueError:
                return (
                    "you haven't uploaded a resume yet. go to **[/upload](/upload)** to upload it first.",
                    None, None,
                )

            if not resume_text.strip():
                return ("your resume appears to be empty. please re-upload at **[/upload](/upload)**.", None, None)

            cost = await CreditsService.get_feature_cost("tailor_resume")
            if cost > 0:
                ok, msg = await CreditsService.deduct_credits(user_id, amount=cost, feature="tailor_resume")
                if not ok:
                    return (f"not enough credits to tailor your resume. {msg}\n\nvisit /pricing to top up.", None, None)

            result      = do_tailor_resume(resume_text, job_description)
            ats_score   = result.get("estimatedATSScore", 0)
            notes       = result.get("optimizationNotes", [])
            notes_md    = "\n".join(f"- {n}" for n in notes[:6])
            orig_struct = await self._get_user_resume_structured(user_id)
            tailored    = _build_tailored_text(result)
            resume_data = _merge_tailored_resume(result, orig_struct)
            score_bd    = result.get("scoreBreakdown", {})

            return (
                f"resume tailored! estimated ATS score: **{ats_score}%**\n\n**key improvements:**\n{notes_md}\n\ndownload your tailored resume below.",
                {
                    "tailored_resume":    tailored,
                    "resume_data":        resume_data,
                    "ats_score":          ats_score,
                    "score_breakdown":    score_bd,
                    "optimization_notes": notes,
                    "job_title":          result.get("jobTitle", ""),
                    "company":            result.get("company", ""),
                },
                "tailored_resume",
            )

        except Exception as e:
            print(f"tailor_resume handler error: {e}")
            if cost > 0:
                await CreditsService.refund_credits(user_id, cost, "tailor_resume via chat failed")
            return (
                "i'm having trouble tailoring your resume right now. try again or use [/tailor](/tailor) directly.",
                None, None,
            )

    # ── Evaluate job ──────────────────────────────────────────────────────

    async def _handle_evaluate_job(
        self, job_description: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            if len(job_description) < 50:
                return (
                    "please paste the full job description text so i can evaluate it. "
                    "or use the **evaluate** button on any job card in [find jobs](/findjob).",
                    None, None,
                )

            try:
                resume_text = await _get_user_resume_text(user_id)
            except ValueError:
                return ("you haven't uploaded a resume yet. go to **[/upload](/upload)** first.", None, None)

            cost = await CreditsService.get_feature_cost("job_evaluate")
            if cost <= 0:
                cost = 1.0
            ok, msg = await CreditsService.deduct_credits(user_id, cost, "job_evaluate")
            if not ok:
                return (f"not enough credits to evaluate this job ({cost:.0f} needed). {msg}\n\n[top up →](/pricing)", None, None)

            from app.routers.job_evaluation_routes import _ghost_job_signals, _signals_to_text
            north_star_doc = await mongo.users.find_one({"_id": ObjectId(user_id)})
            north_star     = ((north_star_doc or {}).get("northStar") or "").strip()
            signals        = _ghost_job_signals(description=job_description, date_posted=None, salary=None)
            signals_text   = _signals_to_text(signals)

            resume_block     = f"\nCandidate's Resume:\n{resume_text[:4000]}\n" if resume_text else "\nCandidate's Resume: Not provided.\n"
            north_star_block = f"\nCandidate's Career Goals:\n{north_star}\n" if north_star else "\nCandidate's Career Goals: Not provided — score axis 3.0.\n"

            prompt = f"""You are a job evaluation assistant. Evaluate this job for the candidate and return ONLY valid JSON.
{resume_block}{north_star_block}
Job Description:
{job_description[:3000]}

Ghost-Job Signals:
{signals_text}

Return JSON:
{{
  "overallGrade": "B+",
  "overallScore": 3.8,
  "verdict": "Worth applying",
  "axes": [
    {{"name": "CV Match", "grade": "A", "score": 4.5, "reasoning": "One sentence."}},
    {{"name": "North Star Alignment", "grade": "B", "score": 3.5, "reasoning": "One sentence."}},
    {{"name": "Compensation vs Market", "grade": "C", "score": 2.5, "reasoning": "One sentence."}},
    {{"name": "Cultural Signals", "grade": "B+", "score": 3.8, "reasoning": "One sentence."}},
    {{"name": "Red Flags", "grade": "A-", "score": 4.2, "reasoning": "One sentence."}},
    {{"name": "Posting Legitimacy", "grade": "B", "score": 3.5, "reasoning": "One sentence."}}
  ]
}}"""

            result = call_ai(prompt, temperature=0.2, max_tokens=1200)
            if "error" in result:
                await CreditsService.refund_credits(user_id, cost, "Job eval via chat AI failed")
                return ("job evaluation failed. please try again.", None, None)

            grade   = result.get("overallGrade", "?")
            score   = float(result.get("overallScore", 0))
            verdict = result.get("verdict", "")
            axes    = result.get("axes", [])
            axes_md = "\n".join(
                f"- **{a['name']}** {a['grade']} ({a['score']:.1f}/5): {a['reasoning']}"
                for a in axes
            )

            return (
                f"**job evaluation: {grade} · {score:.1f}/5**\n\n_{verdict}_\n\n{axes_md}\n\n"
                "_1 credit used · see full details on any job card in [find jobs](/findjob)_",
                {"grade": grade, "score": score, "verdict": verdict, "action": "view_findjob"},
                "job_evaluation",
            )

        except Exception as e:
            print(f"evaluate_job handler error: {e}")
            return ("job evaluation failed. please try again.", None, None)

    # ── Generate follow-up ────────────────────────────────────────────────

    async def _handle_generate_followup(
        self, company: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            cursor = mongo.applications.find({"userId": user_id}).sort("createdAt", -1).limit(20)
            apps   = await cursor.to_list(length=20)

            matched_app = None
            if company:
                for app in apps:
                    if company.lower() in (app.get("company") or "").lower():
                        matched_app = app
                        break
            if not matched_app and apps:
                matched_app = apps[0]

            if not matched_app:
                return (
                    "i couldn't find a tracked application to generate a follow-up for. "
                    "add applications to your [tracker](/tracker) first.",
                    None, None,
                )

            cost = await CreditsService.get_feature_cost("job_followup")
            if cost <= 0:
                cost = 1.0
            ok, credit_msg = await CreditsService.deduct_credits(user_id, cost, "job_followup")
            if not ok:
                return (f"not enough credits for follow-up generation. {credit_msg}\n\n[top up →](/pricing)", None, None)

            from datetime import datetime as _dt, timezone
            created_at = matched_app.get("createdAt") or matched_app.get("created_at")
            try:
                if created_at:
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    days_since = (_dt.now(timezone.utc) - created_at).days
                else:
                    days_since = 0
            except Exception:
                days_since = 0

            comp = matched_app.get("company", "the company")
            role = matched_app.get("jobTitle", "the role")

            prompt = f"""Write a professional follow-up for a job application.
Company: {comp}
Role: {role}
Days since applied: {days_since}

Return ONLY valid JSON:
{{
  "emailDraft": "Professional follow-up email (max 120 words, no subject line)",
  "linkedinDraft": "LinkedIn message (strictly max 300 characters)"
}}"""

            result = call_ai(prompt, temperature=0.4, max_tokens=600)
            if "error" in result:
                await CreditsService.refund_credits(user_id, cost, "Follow-up via chat AI failed")
                return ("follow-up generation failed. please try again.", None, None)

            email    = result.get("emailDraft", "")
            linkedin = result.get("linkedinDraft", "")[:300]

            return (
                f"**follow-up for {comp} — {role}** ({days_since} days since applied)\n\n"
                f"**email draft:**\n{email}\n\n"
                f"**linkedin message:**\n{linkedin}\n\n"
                "_1 credit used · view full details in your [tracker](/tracker)_",
                {"emailDraft": email, "linkedinDraft": linkedin, "company": comp, "action": "view_tracker"},
                "followup_drafts",
            )

        except Exception as e:
            print(f"generate_followup handler error: {e}")
            return ("follow-up generation failed. please try again.", None, None)

    # ── Company research ──────────────────────────────────────────────────

    async def _handle_company_research(
        self, company_name: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            company = company_name.strip()[:80] if company_name else "the company"
            cost    = await CreditsService.get_feature_cost("company_research")
            if cost <= 0:
                cost = 2.0
            ok, credit_msg = await CreditsService.deduct_credits(user_id, cost, "company_research")
            if not ok:
                return (
                    f"not enough credits for company research (needs {cost:.0f}). {credit_msg}\n\n[top up →](/pricing)",
                    None, None,
                )

            prompt = f"""You are a company research analyst. Research {company} for a job seeker preparing for an interview.
Return ONLY valid JSON (no markdown, no extra text):
{{
  "sections": [
    {{"name": "AI/ML Strategy", "bullets": ["...", "..."]}},
    {{"name": "Recent Momentum", "bullets": ["...", "..."]}},
    {{"name": "Engineering Culture", "bullets": ["...", "..."]}},
    {{"name": "Technical Challenges", "bullets": ["...", "..."]}},
    {{"name": "Market Position", "bullets": ["...", "..."]}},
    {{"name": "Personal Fit Tips", "bullets": ["...", "..."]}}
  ]
}}
Each section: 2-3 specific, actionable bullets."""

            result = call_ai(prompt, temperature=0.4, max_tokens=1200)
            if "error" in result:
                await CreditsService.refund_credits(user_id, cost, "Company research via chat AI failed")
                return ("company research failed. try [interview prep](/interview-prep) for the full experience.", None, None)

            sections = result.get("sections", [])
            md_parts = []
            for s in sections:
                bullets = s.get("bullets", [])
                md_parts.append(f"**{s.get('name', '')}**\n" + "\n".join(f"- {b}" for b in bullets))
            summary = "\n\n".join(md_parts) if md_parts else "research complete — open interview prep for details."

            return (
                f"**company research: {company}**\n\n{summary}\n\n"
                "_2 credits used · get the full structured report in [interview prep](/interview-prep)_",
                {"company": company, "action": "view_interview_prep"},
                "company_research",
            )

        except Exception as e:
            print(f"company_research handler error: {e}")
            return ("company research failed. please try again.", None, None)

    # ── Generate outreach ─────────────────────────────────────────────────

    async def _handle_generate_outreach(
        self, context: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            cost = await CreditsService.get_feature_cost("outreach_generate")
            if cost <= 0:
                cost = 1.0
            ok, credit_msg = await CreditsService.deduct_credits(user_id, cost, "outreach_generate")
            if not ok:
                return (f"not enough credits for outreach generation. {credit_msg}\n\n[top up →](/pricing)", None, None)

            prompt = f"""Write a personalized LinkedIn connection message for a job seeker.
Context: {context[:500]}
Keep it professional, specific, and strictly under 300 characters (LinkedIn limit).
Return ONLY valid JSON: {{"message": "...", "characterCount": 250}}"""

            result = call_ai(prompt, temperature=0.4, max_tokens=200)
            if "error" in result:
                await CreditsService.refund_credits(user_id, cost, "Outreach via chat AI failed")
                return ("outreach message generation failed. please try again.", None, None)

            msg_text   = result.get("message", "")[:300]
            char_count = len(msg_text)

            return (
                f"**linkedin message:**\n\n_{msg_text}_\n\n"
                f"_{char_count}/300 characters_\n\n"
                "_1 credit used · generate more messages in your [tracker](/tracker)_",
                {"message": msg_text, "characterCount": char_count, "action": "view_tracker"},
                "outreach_message",
            )

        except Exception as e:
            print(f"generate_outreach handler error: {e}")
            return ("outreach message generation failed. please try again.", None, None)

    # ── Save portfolio URL ─────────────────────────────────────────────────

    async def _handle_save_portfolio_url(
        self, url: str, url_type: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            from app.utils.url_validator import validate_url
            v = await validate_url(url)
            if not v["valid"]:
                return (
                    f"that link doesn't seem to be reachable ({v['reason']}). could you double-check it?",
                    None, None,
                )
            field_map = {
                "portfolio": "portfolio_url",
                "linkedin":  "linkedin_url",
                "github":    "github_url",
                "other":     "portfolio_url",
            }
            field  = field_map.get(url_type, "portfolio_url")
            labels = {"portfolio": "portfolio", "linkedin": "LinkedIn", "github": "GitHub", "other": "portfolio"}
            await mongo.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {field: url}},
            )
            return (
                f"saved your {labels.get(url_type, 'portfolio')} link ✓ — it's on your profile now.",
                None, None,
            )
        except Exception as e:
            print(f"save_portfolio_url error: {e}")
            return ("couldn't save the link right now — try again.", None, None)

    # ── Find freelancers ───────────────────────────────────────────────────

    async def _handle_find_freelancers(
        self, skill: str, location: str, budget_max: float, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            query: Dict = {"available_for_hire": True}
            if skill.strip():
                query["freelance_skills"] = {"$elemMatch": {"$regex": skill.strip(), "$options": "i"}}
            if budget_max > 0:
                query["$or"] = [
                    {"hourly_rate": {"$lte": budget_max}},
                    {"hourly_rate": None},
                    {"hourly_rate": 0},
                ]
            freelancers = []
            async for u in mongo.users.find(query).limit(10):
                if str(u["_id"]) == user_id:
                    continue
                prefs = u.get("job_preferences") or u.get("jobPreferences") or {}
                loc   = prefs.get("preferred_location") or prefs.get("preferredLocation") or ""
                freelancers.append({
                    "user_id":          str(u["_id"]),
                    "name":             f"{u.get('firstName','')} {u.get('lastName','')}".strip(),
                    "freelance_bio":    u.get("freelance_bio"),
                    "freelance_skills": u.get("freelance_skills", []),
                    "hourly_rate":      u.get("hourly_rate"),
                    "portfolio_url":    u.get("portfolio_url"),
                    "linkedin_url":     u.get("linkedin_url"),
                    "github_url":       u.get("github_url"),
                    "location":         loc,
                })
            if not freelancers:
                return (
                    f"no **{skill}** freelancers in our community yet. "
                    "the pool grows as more users enable 'available for hire' on their profile.",
                    None, None,
                )
            budget_str = f"under ${budget_max:.0f}/hr" if budget_max > 0 else "any budget"
            return (
                f"found **{len(freelancers)} {skill} freelancer{'s' if len(freelancers)!=1 else ''}** ({budget_str}):",
                {"freelancers": freelancers, "skill": skill},
                "freelancers_results",
            )
        except Exception as e:
            print(f"find_freelancers error: {e}")
            return ("couldn't search freelancers right now — try again.", None, None)

    # ── Update master resume from chat file upload ─────────────────────────

    async def _handle_update_master_resume(
        self, resume_text: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            from app.services.resume_processor import extract_resume_from_text
            from app.services.incoming_resume_service import IncomingResumeService

            if not resume_text.strip():
                return ("the resume text was empty — please try attaching the file again.", None, None)

            extracted = extract_resume_from_text(resume_text)
            if "error" in extracted:
                return ("couldn't parse that resume — make sure it's a valid PDF, DOCX, or TXT.", None, None)

            await IncomingResumeService.save_or_update(
                user_id=user_id,
                raw_input=resume_text,
                extracted_data=extracted,
            )

            # Auto-save contact URLs
            contact = extracted.get("contact") or {}
            url_patch: Dict = {}
            if contact.get("website"):  url_patch["portfolio_url"] = contact["website"]
            if contact.get("linkedin"): url_patch["linkedin_url"]  = contact["linkedin"]
            if contact.get("github"):   url_patch["github_url"]    = contact["github"]
            if url_patch:
                await mongo.users.update_one({"_id": ObjectId(user_id)}, {"$set": url_patch})

            name = contact.get("name", "your")
            return (
                f"done ✓ — **{name}'s** resume is now your master resume. "
                "i'll use it for all future job matching, tailoring, and evaluations.",
                None, None,
            )
        except Exception as e:
            print(f"update_master_resume error: {e}")
            return ("failed to update your resume — please try again.", None, None)


# Singleton
ai_chat_service = AIChatService()
