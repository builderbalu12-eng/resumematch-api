from typing import Literal


# Define allowed intents
IntentType = Literal[
    "find_jobs",
    "find_leads",
    "find_clients",
    "tailor_resume",
    "resume_advice",
    "skill_guidance",
    "job_info",
    "general_chat",
    "out_of_scope",
    # career-ops intents
    "evaluate_job",
    "generate_followup",
    "company_research",
    "generate_outreach",
]


async def classify_intent(message: str) -> IntentType:
    """
    Classify user intent using Claude.
    """
    if not message or not isinstance(message, str):
        return "out_of_scope"

    try:
        from app.services.ai_provider_service import call_ai_text_async

        prompt = f"""You are classifying messages for ZenLead — an app with these specific features:
1. find_jobs: searches live job listings (Naukri, LinkedIn, Indeed)
2. find_leads: finds local businesses on Google Maps (gyms, salons, restaurants, jewellers, clinics, shops, etc.)
3. find_clients: retrieves the user's already-saved leads from their account
4. tailor_resume: rewrites the user's resume to match a job description and gives ATS score
5. evaluate_job: AI evaluates a job on 6 axes (CV match, salary, culture, etc.) — user mentions evaluating a specific job, asks "should I apply", or pastes a job URL/description for scoring
6. generate_followup: AI writes a follow-up email or LinkedIn message for a job application — user mentions "follow up", "follow-up email", "write a message" for a specific company/application
7. company_research: AI researches a company before an interview — user asks to "research [company]", "prepare for interview at [company]", "tell me about [company] culture"
8. generate_outreach: AI writes a LinkedIn outreach/connection message — user asks to "write a LinkedIn message", "message the hiring manager", "connect with recruiter at [company]"

Classify this user message into ONE of these intents:
find_jobs | find_leads | find_clients | tailor_resume | resume_advice | skill_guidance | job_info | general_chat | out_of_scope | evaluate_job | generate_followup | company_research | generate_outreach

Definitions:
- find_jobs: user wants to search for job listings/vacancies (e.g. "find software engineer jobs in bangalore")
- find_leads: user wants to find NEW business leads, clients, or local businesses in a city
- find_clients: user wants to see their EXISTING saved leads/clients from the database
- tailor_resume: user wants to tailor/customize/optimize their resume for a specific job
- evaluate_job: user wants to evaluate whether a specific job is worth applying to (may paste URL or description)
- generate_followup: user wants to write a follow-up message for a specific job application they already submitted
- company_research: user wants pre-interview intelligence about a company
- generate_outreach: user wants to write a LinkedIn connection/outreach message to someone at a company
- resume_advice: user wants general advice on their resume
- skill_guidance: user wants career or skill development advice
- job_info: user wants information about job trends, salaries
- general_chat: general job/career conversation
- out_of_scope: not related to jobs, careers, or freelancing

RULES (apply in order):
1. Any mention of finding businesses, shops, gyms, salons, clinics, restaurants, jewellers → find_leads
2. "evaluate", "should I apply", "rate this job", "score this job" + job details → evaluate_job
3. "follow up", "follow-up email", "write a message" + application/company context → generate_followup
4. "research [company]", "prepare for interview at", "tell me about [company]" → company_research
5. "LinkedIn message", "message the hiring manager", "outreach message", "connect with recruiter" → generate_outreach
6. Any mention of job listings, vacancies, openings with a location → find_jobs
7. "tailor", "customize", "optimize" + "resume" → tailor_resume

Message: "{message}"

Respond with ONLY the intent name, nothing else. Intent:"""

        intent = await call_ai_text_async(prompt, temperature=0.1, max_tokens=50)
        intent = intent.lower().strip()

        # Clean up the response and validate
        valid_intents = {
            "find_jobs", "find_leads", "find_clients", "tailor_resume",
            "resume_advice", "skill_guidance", "job_info", "general_chat", "out_of_scope",
            "evaluate_job", "generate_followup", "company_research", "generate_outreach",
        }

        # Extract just the intent if there's extra text
        for valid_intent in valid_intents:
            if valid_intent in intent:
                return valid_intent

        # Default fallback
        return "general_chat"

    except Exception as e:
        print(f"Intent classification error: {str(e)}")
        return "general_chat"
