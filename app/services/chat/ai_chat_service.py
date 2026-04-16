import json
import re
import asyncio
from bson import ObjectId
import google.generativeai as genai
from app.services.chat.domain_guard import is_job_related, get_blocked_response
from app.services.chat.intent_classifier import classify_intent
from app.services.job_recommendation_service import (
    JobRecommendationService,
    _scrape_naukri_raw_sync,
    _scrape_jobspy_sync,
)
from app.services.lead_finder import LeadFinder
from app.services.credits_service import CreditsService
from app.services.resume_processor import tailor_resume as do_tailor_resume
from app.services.mongo import mongo
from app.models.chat.schemas import ChatMessage
from typing import List, Dict, Any, Optional, Tuple


# Gemini is configured at startup via init_gemini_config() in main.py.
# No need to re-configure here — genai.configure() is process-global.

# Supported cities / categories for lead extraction
_CITIES = [
    "bangalore", "delhi", "mumbai", "chennai", "kolkata",
    "hyderabad", "pune", "ahmedabad", "jaipur", "surat",
]
_CATEGORIES = [
    "restaurant", "jeweler", "salon", "gym", "clinic", "clothing",
    "bakery", "realestate", "carrepair", "hotel", "cafe", "pharmacy",
    "fitness", "spa", "yoga", "dental", "hospital", "school", "coaching",
    "grocery", "hardware", "electronics", "furniture", "travel", "insurance",
]


_JOB_LOCATIONS = [
    "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad", "pune",
    "chennai", "kolkata", "ahmedabad", "noida", "gurgaon", "gurugram",
    "jaipur", "surat", "india",
]


_CITY_NAMES = (
    "bangalore", "bengaluru", "mumbai", "bombay", "delhi", "new delhi",
    "hyderabad", "pune", "chennai", "madras", "kolkata", "calcutta",
    "ahmedabad", "noida", "gurgaon", "gurugram", "jaipur", "surat",
    "lucknow", "chandigarh", "bhopal", "nagpur", "indore", "coimbatore",
)

# Short fragments that survive common typos (transpositions, extra letters).
# e.g. "clienst" contains "clien", "jwelery" contains "jwel", "resturant" contains "rest"
_BIZ_FRAGMENTS = (
    "clien", "lead", "business", "shop", "store",   # "clien" ⊂ "clienst"
    "gym", "fitnes", "salon", "spa", "yoga",
    "clinic", "dental", "hospit", "pharmac",
    "restaur", "rest",                               # "rest" ⊂ "resturant"
    "cafe", "hotel", "bakery",
    "jwel", "jewel", "jewlr",                        # "jwel" ⊂ "jwelery"
    "cloth", "furn", "electron", "grocer", "school", "coach",
    "travel", "insur", "realest",
)


def _quick_classify(message: str) -> Optional[str]:
    """Regex pre-classifier for unambiguous intent — robust to minor typos."""
    msg = message.lower()

    # find_jobs: word "job/jobs" present
    if re.search(r'\bjobs?\b', msg) and re.search(r'\b(find|search|get|show|list|look)\b', msg):
        return "find_jobs"
    if re.search(r'\bjobs?\b.{0,30}\b(in|at|near)\b', msg):
        return "find_jobs"

    # find_leads: "near/in <city>" + any business fragment — typo-safe
    city_pattern = '|'.join(re.escape(c) for c in _CITY_NAMES)
    near_city = re.search(rf'\b(near|in|at|around)\b.{{0,40}}({city_pattern})', msg)
    has_biz = any(frag in msg for frag in _BIZ_FRAGMENTS)

    if near_city and has_biz:
        return "find_leads"

    # "near [city]" alone — in this app, always a business lead search
    if near_city and not re.search(r'\bjobs?\b', msg):
        return "find_leads"

    # "find/search/get + any business fragment" even without explicit city
    if re.search(r'\b(find|get|search|show|look|help)\b', msg) and has_biz:
        return "find_leads"

    # tailor_resume
    if re.search(r'tailor|customiz|optimis|optimiz', msg) and 'resum' in msg:
        return "tailor_resume"

    return None


_JOB_TITLE_FIXES = {
    "frontd":    "frontend",
    "fronted":   "frontend",
    "frontent":  "frontend",
    "backedn":   "backend",
    "bakend":    "backend",
    "fullstck":  "full stack",
    "fullsatck": "full stack",
    "devloper":  "developer",
    "devlop":    "developer",
    "engneer":   "engineer",
    "enginear":  "engineer",
    "enginer":   "engineer",
    "anaylst":   "analyst",
    "anlyst":    "analyst",
    "managre":   "manager",
    "managar":   "manager",
    "desginer":  "designer",
    "desinger":  "designer",
    "prodcut":   "product",
    "markting":  "marketing",
    "hr":        "human resources",
}


def _parse_job_query(message: str) -> Tuple[str, str]:
    """Extract search term and location from a job-search message."""
    msg = message.lower()
    location = next((loc for loc in _JOB_LOCATIONS if loc in msg), "india")

    # Normalise bengaluru → bangalore for Naukri URL slugs
    naukri_location = "bangalore" if location == "bengaluru" else location

    # Strip common stop words to get the job title
    stop = {
        "find", "me", "show", "get", "search", "for", "in", "at", "near",
        "please", "can", "you", "help", "i", "want", "need", "a", "an",
        "the", "some", "any", "new", "recent", "latest", "jobs", "job",
        "listings", "vacancies", "openings", "positions", "roles",
        location, naukri_location,
    }
    words = re.sub(r"[^\w\s]", "", msg).split()
    search_words = [
        _JOB_TITLE_FIXES.get(w, w)
        for w in words if w not in stop and len(w) > 1
    ]
    search_term = " ".join(search_words).strip() or "software engineer"

    return search_term, naukri_location


_CATEGORY_MAP = {
    # prefix → canonical Google Maps search term
    "jwel":     "jeweler",   # typo: "jwelery" → prefix "jwel"
    "jewel":    "jeweler",
    "jewlr":    "jeweler",
    "restaur":  "restaurant",
    "gym":      "gym",
    "fitness":  "gym",
    "salon":    "salon",
    "spa":      "spa",
    "yoga":     "yoga studio",
    "clinic":   "clinic",
    "dental":   "dentist",
    "hospit":   "hospital",
    "pharmac":  "pharmacy",
    "cafe":     "cafe",
    "bakery":   "bakery",
    "hotel":    "hotel",
    "cloth":    "clothing store",
    "furn":     "furniture store",
    "electron": "electronics store",
    "grocery":  "grocery store",
    "school":   "school",
    "coach":    "coaching center",
    "travel":   "travel agency",
    "insur":    "insurance",
    "realest":  "real estate",
    "carrepair":"car repair",
    "client":   "business",   # generic fallback when user says "clients"
    "business": "business",
    "shop":     "shop",
    "store":    "store",
}


def _extract_city_category_radius(message: str) -> Tuple[str, str, float]:
    """Extract city, category and radius — prefix-matched to handle typos."""
    msg = message.lower()

    # City: check all known city names (longest match wins)
    city = "bangalore"
    for c in sorted(_CITY_NAMES, key=len, reverse=True):
        if c in msg:
            city = c
            break
    # Normalise bengaluru → bangalore for Naukri slugs
    if city in ("bengaluru", "bombay", "madras", "calcutta"):
        city = {"bengaluru": "bangalore", "bombay": "mumbai",
                "madras": "chennai", "calcutta": "kolkata"}[city]

    # Category: prefix matching
    category = "business"  # safe default
    for prefix, canonical in _CATEGORY_MAP.items():
        if prefix in msg:
            category = canonical
            break

    m = re.search(r"(\d+)\s*km", msg)
    radius = float(m.group(1)) if m else 5.0
    return city, category, radius


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

    # Fallback: raw text field
    return doc.get("raw_text") or doc.get("text") or ""


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
            # Step 1: Domain guard
            if not is_job_related(message):
                return {
                    "response": get_blocked_response(),
                    "intent": "out_of_scope",
                    "action_type": None,
                    "action_data": None,
                    "success": True,
                }

            # Step 2: Classify intent (fast regex first, Gemini as fallback)
            intent = _quick_classify(message) or await classify_intent(message)
            action_type: Optional[str] = None
            action_data: Optional[Dict[str, Any]] = None

            # Step 3: Route
            if intent == "find_jobs":
                response, action_data, action_type = await self._handle_find_jobs(message, user_id)
            elif intent == "find_leads":
                response, action_data, action_type = await self._handle_find_leads(message, user_id)
            elif intent == "find_clients":
                response, action_data, action_type = await self._handle_find_clients(message, user_id)
            elif intent == "tailor_resume":
                response, action_data, action_type = await self._handle_tailor_resume(message, user_id)
            elif intent in ("resume_advice", "skill_guidance", "job_info", "general_chat"):
                response = await self._handle_conversational(message, session_history, intent)
            else:
                response = get_blocked_response()
                intent = "out_of_scope"

            return {
                "response": response,
                "intent": intent,
                "action_type": action_type,
                "action_data": action_data,
                "success": True,
            }

        except Exception as e:
            print(f"AI Chat Service error: {str(e)}")
            return {
                "response": "I'm having trouble processing your request. Please try again.",
                "intent": "error",
                "action_type": None,
                "action_data": None,
                "success": False,
            }

    # ── Find jobs ──────────────────────────────────────────────────────────
    async def _handle_find_jobs(
        self, message: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            cost = await CreditsService.get_feature_cost("find_jobs")

            # Check user has enough credits before running the scraper
            if cost > 0:
                user_doc = await mongo.users.find_one({"_id": ObjectId(user_id)})
                balance = float(user_doc.get("credits", 0)) if user_doc else 0.0
                if balance < cost:
                    return (
                        f"You don't have enough credits to search for jobs (need {cost:.0f} credits, you have {balance:.0f}).\n\nVisit /pricing to top up.",
                        None, None,
                    )

            search_term, location = _parse_job_query(message)
            loop = asyncio.get_event_loop()

            # Try Naukri raw scraper first (no external deps)
            raw_results: List[Dict] = await loop.run_in_executor(
                None,
                lambda: _scrape_naukri_raw_sync(search_term, location, pages=2),
            )

            # Fallback to JobSpy (LinkedIn/Indeed) if Naukri returns nothing
            if not raw_results:
                raw_results = await loop.run_in_executor(
                    None,
                    lambda: _scrape_jobspy_sync(
                        search_term=search_term,
                        location=location,
                        results_per_site=5,
                        hours_old=72,
                        sites=["linkedin", "indeed"],
                        country_indeed="india",
                        is_remote=None,
                        proxies=None,
                    ),
                )

            if not raw_results:
                return (
                    f"I couldn't find jobs for *{search_term}* in *{location}* right now. No credits were deducted. Try a different role or city — e.g. *'Python developer jobs in Mumbai'*.",
                    None, None,
                )

            # Only deduct credits when results are actually found
            if cost > 0:
                ok, deduct_msg = await CreditsService.deduct_credits(user_id, amount=cost, feature="find_jobs")
                if not ok:
                    return (
                        f"Credit deduction failed. {deduct_msg}\n\nVisit /pricing to top up.",
                        None, None,
                    )

            jobs = [
                {
                    "Title": j.get("title", ""),
                    "Company": j.get("company", ""),
                    "Location": j.get("location", ""),
                    "Experience": j.get("experience", ""),
                    "Salary": j.get("salary", ""),
                    "Site": j.get("site", ""),
                    "Type": j.get("job_type", ""),
                    "URL": j.get("job_url", ""),
                }
                for j in raw_results[:20]
            ]
            return (
                f"Found **{len(jobs)} {search_term} jobs** in {location.title()}. Download the spreadsheet below.",
                {"jobs": jobs, "count": len(jobs)},
                "jobs_results",
            )

        except Exception as e:
            print(f"find_jobs handler error: {e}")
            return ("I'm having trouble searching for jobs right now. Please try again.", None, None)

    # ── Find leads (Google Maps) ───────────────────────────────────────────
    async def _handle_find_leads(
        self, message: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            cost = await CreditsService.get_feature_cost("find_leads")

            # Determine how many leads the user can afford
            if cost > 0:
                user_doc = await mongo.users.find_one({"_id": ObjectId(user_id)})
                balance = float(user_doc.get("credits", 0)) if user_doc else 0.0
                max_affordable = int(balance // cost)
                if max_affordable == 0:
                    return (
                        f"You don't have enough credits to find leads (need at least {cost:.0f} credits, you have {balance:.0f}).\n\nVisit /pricing to top up.",
                        None, None,
                    )
                scraper_limit = min(20, max_affordable)
            else:
                scraper_limit = 20

            city, category, radius = _extract_city_category_radius(message)

            raw_leads = await self.lead_finder.find_and_save_leads(
                city=city,
                category=category,
                radius_km=radius,
                owner_id=user_id,
                mongo=mongo,
                limit=scraper_limit,
            )

            if not raw_leads:
                return (
                    f"I couldn't find leads for *{category}* in *{city}*. Try a different city or category.",
                    None, None,
                )

            # Deduct cost × actual leads found (per-lead billing)
            if cost > 0:
                total_cost = cost * len(raw_leads)
                ok, msg = await CreditsService.deduct_credits(user_id, amount=total_cost, feature="find_leads")
                if not ok:
                    return (
                        f"Credit deduction failed after finding leads. {msg}\n\nVisit /pricing to top up.",
                        None, None,
                    )

            leads = [
                {
                    "Name": l.get("name", ""),
                    "Phone": l.get("phone", ""),
                    "Address": l.get("address", ""),
                    "Website": l.get("website", ""),
                    "Has Website": "Yes" if l.get("has_website") else "No",
                    "Rating": l.get("rating", ""),
                    "Category": l.get("category", category),
                }
                for l in raw_leads
            ]
            return (
                f"Found **{len(leads)} leads** in {city.title()} ({category}). Download the spreadsheet below.",
                {"leads": leads, "count": len(leads), "city": city, "category": category},
                "leads_results",
            )

        except Exception as e:
            print(f"find_leads handler error: {e}")
            return ("I'm having trouble finding leads right now. Please try again.", None, None)

    # ── Find clients (existing DB leads) ──────────────────────────────────
    async def _handle_find_clients(
        self, message: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            msg = message.lower()
            category = next((c for c in _CATEGORIES if c in msg), None)

            query: Dict[str, Any] = {"owner_id": user_id}
            if category:
                query["category"] = category

            cursor = mongo.clients.find(query).sort("created_at", -1).limit(50)
            clients = await cursor.to_list(length=50)

            if clients:
                leads = [
                    {
                        "Name": c.get("name", ""),
                        "Category": c.get("category", ""),
                        "Phone": c.get("phone", ""),
                        "Address": c.get("address", ""),
                        "Website": c.get("website", ""),
                        "Has Website": "Yes" if c.get("has_website") else "No",
                        "Status": c.get("status", "lead"),
                    }
                    for c in clients
                ]
                label = f"for *{category}*" if category else ""
                return (
                    f"Found **{len(leads)} existing leads** {label} in your database. Download the spreadsheet below.",
                    {"leads": leads, "count": len(leads)},
                    "leads_results",
                )
            else:
                if category:
                    return (
                        f"You don't have any existing leads for *{category}*. Want me to find new ones? Just say which city.",
                        None, None,
                    )
                return (
                    "You don't have any saved leads yet. Want me to find some? Tell me a city and business category.",
                    None, None,
                )

        except Exception as e:
            print(f"find_clients handler error: {e}")
            return ("I'm having trouble retrieving your leads right now. Please try again.", None, None)

    # ── Tailor resume ──────────────────────────────────────────────────────
    async def _handle_tailor_resume(
        self, message: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        cost = 0.0
        try:
            # Fetch resume first — don't deduct credits if user has none
            try:
                resume_text = await _get_user_resume_text(user_id)
            except ValueError:
                return (
                    "You haven't uploaded a resume yet. Please go to **[/upload](/upload)** to upload your master resume first, then come back here.",
                    None, None,
                )

            if not resume_text.strip():
                return (
                    "Your resume appears to be empty. Please re-upload it at **[/upload](/upload)**.",
                    None, None,
                )

            cost = await CreditsService.get_feature_cost("tailor_resume")
            if cost > 0:
                ok, msg = await CreditsService.deduct_credits(user_id, amount=cost, feature="tailor_resume")
                if not ok:
                    return (
                        f"You don't have enough credits to tailor your resume. {msg}\n\nVisit /pricing to top up.",
                        None, None,
                    )

            # Use the full message as the job description
            result = do_tailor_resume(resume_text, message)

            tailored = result.get("tailoredResume", "")
            ats_score = result.get("estimatedATSScore", 0)
            notes = result.get("optimizationNotes", [])

            notes_md = "\n".join(f"- {n}" for n in notes[:6])
            response_text = (
                f"Resume tailored! Estimated ATS score: **{ats_score}%**\n\n"
                f"**Key improvements:**\n{notes_md}\n\n"
                "Download your tailored resume below."
            )

            return (
                response_text,
                {"tailored_resume": tailored, "ats_score": ats_score, "optimization_notes": notes},
                "tailored_resume",
            )

        except Exception as e:
            print(f"tailor_resume handler error: {e}")
            if cost > 0:
                await CreditsService.refund_credits(user_id, cost, "tailor_resume via chat failed")
            return (
                "I'm having trouble tailoring your resume right now. Please try again or use the [/tailor](/tailor) page directly.",
                None, None,
            )

    # ── Conversational ─────────────────────────────────────────────────────
    async def _handle_conversational(
        self,
        message: str,
        session_history: List[ChatMessage],
        intent: str,
    ) -> str:
        try:
            _APP_CONTEXT = (
                "You are Maya, the AI assistant for ZenLead — an all-in-one platform for job seekers and freelancers.\n\n"
                "## What ZenLead can do (your built-in features):\n"
                "1. **Find Jobs** — Search live job listings from Naukri, LinkedIn, and Indeed.\n"
                "   → Trigger phrase: 'find [role] jobs in [city]' (e.g. 'find software engineer jobs in Bangalore')\n"
                "2. **Find Business Leads** — Find local businesses on Google Maps (gyms, salons, restaurants, jewellers, clinics, etc.) by city.\n"
                "   → Trigger phrase: 'find [business type] near [city]' (e.g. 'find gyms near Delhi', 'find clients related to salon in Mumbai')\n"
                "3. **Tailor Resume** — Customize the user's uploaded resume to match a specific job description and get an ATS score.\n"
                "   → Trigger phrase: 'tailor my resume for [job description]'\n\n"
                "## How to respond:\n"
                "- If the user is asking about something these features can handle, ALWAYS guide them to use the right trigger phrase.\n"
                "- Do NOT give generic advice when a feature can actually do the work. Instead say: 'I can do that for you! Just say: find [X] near [city]'\n"
                "- If someone mentions finding businesses, clients, leads, gyms, salons, shops, or any local service — suggest the lead finder.\n"
                "- If someone wants job listings or vacancies — suggest the job finder.\n"
                "- If someone wants to optimize their resume for a job — suggest the resume tailor.\n"
                "- Only answer conversationally for things that genuinely need advice (e.g. 'how do I write a cover letter?').\n"
            )

            system_prompts = {
                "resume_advice": "You are a resume expert. Provide specific, actionable advice for improving resumes, formatting, content, and tailoring for specific jobs.",
                "skill_guidance": "You are a career counselor. Provide guidance on skill development, learning paths, and career progression.",
                "job_info": "You are a job market expert. Provide information about job trends, salary expectations, and career opportunities.",
                "general_chat": "You are a helpful job and career assistant. Answer questions about jobs, resumes, careers, and professional development.",
            }
            system_prompt = system_prompts.get(intent, system_prompts["general_chat"])

            from app.services.ai_provider_service import call_ai_chat_async
            from app.services.gemini_config_service import get_active_config_sync
            _gcfg = get_active_config_sync()

            system_instruction = (
                f"{_APP_CONTEXT}\n\n"
                f"{system_prompt}\n\n"
                "Only answer job, resume, career, freelancing, and hiring related questions. "
                "Never go outside this domain."
            )

            history = []
            for msg in session_history[-10:]:
                role = "user" if msg.role.value == "user" else "model"
                history.append({"role": role, "parts": [msg.content]})

            return await call_ai_chat_async(
                history=history,
                user_message=message,
                system_instruction=system_instruction,
                temperature=_gcfg["temperature"],
                max_tokens=_gcfg["max_tokens"],
            )

        except Exception as e:
            print(f"Conversational AI error: {e}")
            return "I'm having trouble generating a response right now. Please try again."


# Singleton
ai_chat_service = AIChatService()
