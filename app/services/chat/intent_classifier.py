import google.generativeai as genai
from app.config import settings
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
    "out_of_scope"
]


# Initialize Gemini
genai.configure(api_key=settings.gemini_api_key)


async def classify_intent(message: str) -> IntentType:
    """
    Classify user intent using Gemini AI.
    
    Args:
        message: User message to classify
        
    Returns:
        Intent classification as string
    """
    if not message or not isinstance(message, str):
        return "out_of_scope"
    
    try:
        model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            generation_config={
                "temperature": 0.1,  # Low temperature for consistent classification
                "max_output_tokens": 50,  # Keep it short
                "top_p": 0.8,
                "top_k": 40
            }
        )
        
        prompt = f"""You are classifying messages for ZenLead — an app with these specific features:
1. find_jobs: searches live job listings (Naukri, LinkedIn, Indeed)
2. find_leads: finds local businesses on Google Maps (gyms, salons, restaurants, jewellers, clinics, shops, etc.)
3. find_clients: retrieves the user's already-saved leads from their account
4. tailor_resume: rewrites the user's resume to match a job description and gives ATS score

Classify this user message into ONE of these intents:
find_jobs | find_leads | find_clients | tailor_resume | resume_advice | skill_guidance | job_info | general_chat | out_of_scope

Definitions:
- find_jobs: user wants to search for job listings/vacancies (e.g. "find software engineer jobs in bangalore")
- find_leads: user wants to find NEW business leads, clients, or local businesses in a city (e.g. "find gyms near delhi", "find clients related to salon in mumbai", "find restaurants in pune", "find jewellery shops near delhi")
- find_clients: user wants to see their EXISTING saved leads/clients from the database
- tailor_resume: user wants to tailor/customize/optimize their resume for a specific job
- resume_advice: user wants general advice on their resume (no specific job description given)
- skill_guidance: user wants career or skill development advice
- job_info: user wants information about job trends, salaries — NOT asking to search listings
- general_chat: general job/career conversation
- out_of_scope: not related to jobs, careers, or freelancing

RULES (apply in order):
1. Any mention of finding businesses, shops, gyms, salons, clinics, restaurants, jewellers, or ANY local service "near", "in", or "around" a location → ALWAYS find_leads
2. Any mention of job listings, vacancies, openings with a location → find_jobs
3. "tailor", "customize", "optimize" + "resume" → tailor_resume
4. Asking to view/show their saved clients/leads → find_clients
5. Typos are common — e.g. "clienst" = clients, "jwelery" = jewellery, "resturant" = restaurant. Still classify based on intent.

Message: "{message}"

Respond with ONLY the intent name, nothing else. Intent:"""
        
        response = await model.generate_content_async(prompt)
        intent = response.text.strip().lower()
        
        # Clean up the response and validate
        valid_intents = {
            "find_jobs", "find_leads", "find_clients", "tailor_resume",
            "resume_advice", "skill_guidance", "job_info", "general_chat", "out_of_scope"
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
