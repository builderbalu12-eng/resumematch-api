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

    # evaluate_job
    if re.search(r'\bevaluat|should i apply|rate this job|score this job|is this job', msg):
        return "evaluate_job"

    # generate_followup
    if re.search(r'follow.?up|follow-up email|write.*message.*appli|message.*follow', msg):
        return "generate_followup"

    # company_research
    if re.search(r'research (the )?company|research .{1,40} (before|for) interview|prepare for interview at|tell me about .{1,40} culture|company intel', msg):
        return "company_research"

    # generate_outreach
    if re.search(r'linkedin message|outreach message|message the hiring|message.*recruiter|connect with.*at\b', msg):
        return "generate_outreach"

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
            elif intent == "evaluate_job":
                response, action_data, action_type = await self._handle_evaluate_job(message, user_id)
            elif intent == "generate_followup":
                response, action_data, action_type = await self._handle_generate_followup(message, user_id)
            elif intent == "company_research":
                response, action_data, action_type = await self._handle_company_research(message, user_id)
            elif intent == "generate_outreach":
                response, action_data, action_type = await self._handle_generate_outreach(message, user_id)
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

            # Load user profile context upfront (used for credits + smart search)
            user_doc = await mongo.users.find_one({"_id": ObjectId(user_id)})
            if not user_doc:
                return ("User not found.", None, None)

            if cost > 0:
                balance = float(user_doc.get("credits", 0))
                if balance < cost:
                    return (
                        f"You don't have enough credits to search for jobs (need {cost:.0f} credits, you have {balance:.0f}).\n\nVisit /pricing to top up.",
                        None, None,
                    )

            # Parse what the user typed
            msg_role, msg_location = _parse_job_query(message)

            # Detect vague queries — words that aren't real job titles
            _VAGUE_WORDS = {
                "matching", "match", "profile", "skill", "skills", "my",
                "suitable", "relevant", "related", "appropriate", "good",
                "fit", "fits", "based", "background", "experience",
                "help", "software", "developer",  # too generic without context
            }
            msg_words = set(msg_role.lower().split())
            is_vague = len(msg_words - _VAGUE_WORDS) == 0

            # Pull preferred role / location from saved preferences or resume
            prefs = user_doc.get("jobPreferences") or user_doc.get("job_preferences") or {}
            pref_role = prefs.get("desired_role") or prefs.get("desiredRole") or ""
            pref_location = prefs.get("preferred_location") or prefs.get("preferredLocation") or ""

            # If message is vague and we have no profile prefs, try to read from resume
            if is_vague and not pref_role:
                try:
                    resume_text = await _get_user_resume_text(user_id)
                    if resume_text:
                        # Ask Gemini to extract role + location from resume
                        model = genai.GenerativeModel("gemini-1.5-flash")
                        extract_prompt = (
                            f"From this resume extract the most recent or target job role and the city.\n"
                            f"Reply ONLY as JSON: {{\"role\": \"...\", \"city\": \"...\"}}\n\n{resume_text[:2000]}"
                        )
                        ext_resp = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: model.generate_content(extract_prompt)
                        )
                        raw = ext_resp.text.strip().strip("```json").strip("```").strip()
                        extracted = json.loads(raw)
                        pref_role = extracted.get("role", "") or pref_role
                        pref_location = extracted.get("city", "") or pref_location
                except Exception:
                    pass

            # Use profile context when message is vague
            search_term = pref_role if (is_vague and pref_role) else msg_role
            location = pref_location.lower() if (msg_location == "india" and pref_location) else msg_location

            # Normalise bengaluru
            if "bengaluru" in location:
                location = "bangalore"
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

            # Cap at 5 jobs for individual card display
            top_results = raw_results[:5]
            jobs_base = [
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
                for j in top_results
            ]

            # Generate a short personal pitch per job using Gemini
            try:
                user_role = pref_role or search_term

                pitch_prompt = (
                    f"You are writing a brief, personal outreach pitch for a job seeker targeting: {user_role}.\n"
                    f"For each job below, write a 1-2 sentence lowercase conversational pitch explaining why this role fits them. "
                    f"Be specific and encouraging. Output ONLY a JSON array of strings (one per job).\n\n"
                    + "\n".join(f"{i+1}. {j['Title']} at {j['Company']} ({j['Location']})" for i, j in enumerate(jobs_base))
                )
                model = genai.GenerativeModel("gemini-1.5-flash")
                resp = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: model.generate_content(pitch_prompt)
                )
                raw_text = resp.text.strip()
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("```")[1]
                    if raw_text.startswith("json"):
                        raw_text = raw_text[4:]
                pitches = json.loads(raw_text.strip())
                for i, job in enumerate(jobs_base):
                    job["pitch"] = pitches[i] if i < len(pitches) else ""
            except Exception as pe:
                print(f"Pitch generation failed: {pe}")
                for job in jobs_base:
                    job.setdefault("pitch", "")

            return (
                f"here are the top **{len(jobs_base)} {search_term} roles** i found in {location.title()} ✨",
                {"jobs": jobs_base, "count": len(jobs_base)},
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

    # ── Evaluate Job ──────────────────────────────────────────────────────
    async def _handle_evaluate_job(
        self, message: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            from app.services.ai_provider_service import call_ai

            # Extract description from message (use message itself as description)
            # Try to extract a URL from the message
            url_match = re.search(r'https?://\S+', message)
            job_url = url_match.group(0) if url_match else ""

            # Build minimal request — use message as description
            description = message if not job_url else message.replace(job_url, "").strip()
            if len(description) < 50:
                return (
                    "To evaluate a job, please paste the job description text (or URL) in your message. "
                    "For example: *'Evaluate this job: [paste job description here]'*\n\n"
                    "Or use the **Evaluate** button on any job card in [Find Jobs](/findjob).",
                    None, None,
                )

            # Fetch user's resume
            try:
                resume_text = await _get_user_resume_text(user_id)
            except ValueError:
                return (
                    "You haven't uploaded a resume yet. Please go to **[/upload](/upload)** first.",
                    None, None,
                )

            # Check / deduct credits
            cost = await CreditsService.get_feature_cost("job_evaluate")
            if cost <= 0:
                cost = 1.0

            # Cache check
            from app.services.mongo import mongo as _mongo
            cached = await _mongo.job_evaluations.find_one({"userId": user_id, "jobUrl": job_url}) if job_url else None
            if cached:
                ev = cached.get("evaluationResult", {})
                grade = ev.get("overallGrade", "?")
                score = ev.get("overallScore", 0)
                verdict = ev.get("verdict", "")
                return (
                    f"**Job Evaluation (cached):** {grade} · {score:.1f}/5\n\n_{verdict}_\n\n"
                    "View the full breakdown on any evaluated job card in [Find Jobs](/findjob).",
                    {"grade": grade, "score": score, "verdict": verdict, "action": "view_evaluation"},
                    "job_evaluation",
                )

            ok, msg = await CreditsService.deduct_credits(user_id, cost, "job_evaluate")
            if not ok:
                return (
                    f"Not enough credits to evaluate this job ({cost:.0f} needed). {msg}\n\n[Top up credits →](/pricing)",
                    None, None,
                )

            from app.routers.job_evaluation_routes import _get_resume_text, _ghost_job_signals, _signals_to_text
            from bson import ObjectId

            north_star_doc = await _mongo.users.find_one({"_id": ObjectId(user_id)})
            north_star = ((north_star_doc or {}).get("northStar") or "").strip()
            signals = _ghost_job_signals(description=description, date_posted=None, salary=None)
            signals_text = _signals_to_text(signals)

            resume_block = f"\nCandidate's Resume:\n{resume_text[:4000]}\n" if resume_text else "\nCandidate's Resume: Not provided.\n"
            north_star_block = f"\nCandidate's Career Goals:\n{north_star}\n" if north_star else "\nCandidate's Career Goals: Not provided — score axis 3.0.\n"

            prompt = f"""You are a job evaluation assistant. Evaluate this job for the candidate and return ONLY valid JSON.
{resume_block}{north_star_block}
Job Description:
{description[:3000]}

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
                return ("Job evaluation failed. Please try again.", None, None)

            grade = result.get("overallGrade", "?")
            score = float(result.get("overallScore", 0))
            verdict = result.get("verdict", "")
            axes = result.get("axes", [])

            axes_md = "\n".join(
                f"- **{a['name']}** {a['grade']} ({a['score']:.1f}/5): {a['reasoning']}"
                for a in axes
            )

            return (
                f"**Job Evaluation: {grade} · {score:.1f}/5**\n\n_{verdict}_\n\n{axes_md}\n\n"
                "_1 credit used · See full details on any job card in [Find Jobs](/findjob)_",
                {"grade": grade, "score": score, "verdict": verdict, "action": "view_findjob"},
                "job_evaluation",
            )

        except Exception as e:
            print(f"evaluate_job handler error: {e}")
            return ("Job evaluation failed. Please try again.", None, None)

    # ── Generate Follow-up ───────────────────────────────────────────────
    async def _handle_generate_followup(
        self, message: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            from app.services.ai_provider_service import call_ai
            from app.services.mongo import mongo as _mongo

            # Try to find a matching application from the message
            msg_lower = message.lower()
            cursor = _mongo.applications.find({"userId": user_id}).sort("createdAt", -1).limit(20)
            apps = await cursor.to_list(length=20)

            matched_app = None
            for app in apps:
                company = (app.get("company") or "").lower()
                if company and company in msg_lower:
                    matched_app = app
                    break

            if not matched_app and apps:
                matched_app = apps[0]  # Use most recent if no match

            if not matched_app:
                return (
                    "I couldn't find a tracked application to generate a follow-up for. "
                    "Add applications to your [Tracker](/tracker) first, then ask me to write a follow-up.",
                    None, None,
                )

            cost = await CreditsService.get_feature_cost("job_followup")
            if cost <= 0:
                cost = 1.0
            ok, credit_msg = await CreditsService.deduct_credits(user_id, cost, "job_followup")
            if not ok:
                return (
                    f"Not enough credits for follow-up generation. {credit_msg}\n\n[Top up →](/pricing)",
                    None, None,
                )

            from datetime import datetime, timezone
            created_at = matched_app.get("createdAt") or matched_app.get("created_at")
            try:
                if created_at:
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    days_since = (datetime.now(timezone.utc) - created_at).days
                else:
                    days_since = 0
            except Exception:
                days_since = 0
            company = matched_app.get("company", "the company")
            role = matched_app.get("jobTitle", "the role")

            prompt = f"""Write a professional follow-up for a job application.
Company: {company}
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
                return ("Follow-up generation failed. Please try again.", None, None)

            email = result.get("emailDraft", "")
            linkedin = result.get("linkedinDraft", "")[:300]

            return (
                f"**Follow-up for {company} — {role}** ({days_since} days since applied)\n\n"
                f"**Email draft:**\n{email}\n\n"
                f"**LinkedIn message:**\n{linkedin}\n\n"
                "_1 credit used · View full details in your [Tracker](/tracker)_",
                {"emailDraft": email, "linkedinDraft": linkedin, "company": company, "action": "view_tracker"},
                "followup_drafts",
            )

        except Exception as e:
            print(f"generate_followup handler error: {e}")
            return ("Follow-up generation failed. Please try again.", None, None)

    # ── Company Research ─────────────────────────────────────────────────
    async def _handle_company_research(
        self, message: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            from app.services.ai_provider_service import call_ai

            # Extract company name from message
            # Remove common preamble phrases to get the company name
            clean = re.sub(
                r"(research|tell me about|prepare for interview at|before my interview at|company intel for|about)\s+",
                "", message, flags=re.IGNORECASE
            ).strip().rstrip("?.")
            company = clean[:80] if clean else "the company"

            cost = await CreditsService.get_feature_cost("company_research")
            if cost <= 0:
                cost = 2.0
            ok, credit_msg = await CreditsService.deduct_credits(user_id, cost, "company_research")
            if not ok:
                return (
                    f"Not enough credits for company research (needs {cost:.0f}). {credit_msg}\n\n[Top up →](/pricing)",
                    None, None,
                )

            prompt = f"""You are a company research analyst. Research {company} for a job seeker preparing for an interview.
Return ONLY valid JSON with this structure (no markdown, no extra text):
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
Each section: 2-3 bullets. Be specific and actionable."""

            result = call_ai(prompt, temperature=0.4, max_tokens=1200)

            if "error" in result:
                await CreditsService.refund_credits(user_id, cost, "Company research via chat AI failed")
                return ("Company research failed. Please try the [Interview Prep](/interview-prep) page for the full experience.", None, None)

            sections = result.get("sections", [])
            md_parts = []
            for s in sections:
                name = s.get("name", "")
                bullets = s.get("bullets", [])
                md_parts.append(f"**{name}**\n" + "\n".join(f"- {b}" for b in bullets))
            summary = "\n\n".join(md_parts) if md_parts else "Research complete — open Interview Prep for details."

            return (
                f"**Company Research: {company}**\n\n{summary}\n\n"
                "_2 credits used · Get the full structured report in [Interview Prep](/interview-prep)_",
                {"company": company, "action": "view_interview_prep"},
                "company_research",
            )

        except Exception as e:
            print(f"company_research handler error: {e}")
            return ("Company research failed. Please try again.", None, None)

    # ── Generate Outreach ────────────────────────────────────────────────
    async def _handle_generate_outreach(
        self, message: str, user_id: str
    ) -> Tuple[str, Optional[Dict], Optional[str]]:
        try:
            from app.services.ai_provider_service import call_ai
            from app.services.mongo import mongo as _mongo

            cost = await CreditsService.get_feature_cost("outreach_generate")
            if cost <= 0:
                cost = 1.0
            ok, credit_msg = await CreditsService.deduct_credits(user_id, cost, "outreach_generate")
            if not ok:
                return (
                    f"Not enough credits for outreach generation. {credit_msg}\n\n[Top up →](/pricing)",
                    None, None,
                )

            # Extract company/role from message
            company_match = re.search(r'\bat\s+([A-Z][a-zA-Z0-9\s&.]{1,40})', message)
            company = company_match.group(1).strip() if company_match else "the company"

            prompt = f"""Write a personalized LinkedIn connection message for a job seeker reaching out to a hiring contact at {company}.
The message should be professional, specific, and strictly under 300 characters (LinkedIn limit).
User message context: {message[:300]}
Return ONLY valid JSON: {{"message": "...", "characterCount": 250}}"""

            result = call_ai(prompt, temperature=0.4, max_tokens=200)
            if "error" in result:
                await CreditsService.refund_credits(user_id, cost, "Outreach via chat AI failed")
                return ("Outreach message generation failed. Please try again.", None, None)

            msg_text = result.get("message", "")[:300]
            char_count = len(msg_text)

            return (
                f"**LinkedIn Message for {company}:**\n\n_{msg_text}_\n\n"
                f"_{char_count}/300 characters_\n\n"
                "_1 credit used · Generate more tailored messages in your [Tracker](/tracker)_",
                {"message": msg_text, "characterCount": char_count, "company": company, "action": "view_tracker"},
                "outreach_message",
            )

        except Exception as e:
            print(f"generate_outreach handler error: {e}")
            return ("Outreach message generation failed. Please try again.", None, None)

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
