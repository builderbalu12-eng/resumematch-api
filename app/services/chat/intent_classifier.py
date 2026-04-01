import google.generativeai as genai
from app.config import settings
from typing import Literal


# Define allowed intents
IntentType = Literal[
    "find_jobs",
    "find_leads", 
    "find_clients",
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
        
        prompt = f"""Classify this user message into ONE of these intents:
find_jobs | find_leads | find_clients | resume_advice | skill_guidance | job_info | general_chat | out_of_scope

Message: "{message}"

Intent:"""
        
        response = await model.generate_content_async(prompt)
        intent = response.text.strip().lower()
        
        # Clean up the response and validate
        valid_intents = {
            "find_jobs", "find_leads", "find_clients", "resume_advice", 
            "skill_guidance", "job_info", "general_chat", "out_of_scope"
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
