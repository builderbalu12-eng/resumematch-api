import re
from typing import List


ALLOWED_KEYWORDS: List[str] = [
    # Core domain terms
    "job", "resume", "career", "skill", "salary", "interview",
    "hiring", "recruiter", "work", "internship", "freelance", "freelancing",
    "lead", "client", "linkedin", "naukri", "company", "role",
    "apply", "placement", "hr", "employment", "profession",
    "vacancy", "opening", "position", "occupation", "workplace",
    "business", "customer", "prospect", "sales",
    "earn", "earning", "income", "rate", "charge", "fee",
    "contract", "project", "portfolio", "profile",
    "startup", "entrepreneur", "self-employed",
    "payment", "invoice", "gig", "remote", "hybrid",
    "promotion", "appraisal", "raise", "growth",
    "certification", "course", "learn", "upskill",
    "network", "connection", "referral",
    # Action verbs / request phrases — so "can you search jobs" isn't blocked
    "search", "find", "look", "show", "get", "give", "help",
    "suggest", "recommend", "tell", "list", "need", "want",
]


BLOCKED_RESPONSE = (
    "This assistant is restricted to job-related queries only. "
    "Ask me about jobs, resume, career advice, or finding leads."
)


def is_job_related(text: str) -> bool:
    """
    Check if message contains job-related keywords.
    
    Args:
        text: User message to check
        
    Returns:
        bool: True if job-related, False if blocked
    """
    if not text or not isinstance(text, str):
        return False
    
    # Convert to lowercase for case-insensitive matching
    text_lower = text.lower()
    
    # Check if any allowed keyword is present
    for keyword in ALLOWED_KEYWORDS:
        if re.search(rf'\b{re.escape(keyword)}\b', text_lower):
            return True
    
    return False


def get_blocked_response() -> str:
    """Return the standard blocked response message."""
    return BLOCKED_RESPONSE
