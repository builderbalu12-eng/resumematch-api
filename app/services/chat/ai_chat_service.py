import google.generativeai as genai
from app.config import settings
from app.services.chat.domain_guard import is_job_related, get_blocked_response
from app.services.chat.intent_classifier import classify_intent
from app.services.job_recommendation_service import JobRecommendationService
from app.services.lead_finder import LeadFinder
from app.services.mongo import mongo
from app.models.chat.schemas import ChatMessage
from typing import List, Dict, Any


# Initialize Gemini
genai.configure(api_key=settings.gemini_api_key)


class AIChatService:
    
    def __init__(self):
        self.job_service = JobRecommendationService()
        self.lead_finder = LeadFinder()
    
    async def process_message(
        self, 
        user_id: str, 
        message: str, 
        session_history: List[ChatMessage]
    ) -> Dict[str, Any]:
        """
        Process user message and generate AI response.
        
        Args:
            user_id: User identifier
            message: User message
            session_history: Previous messages in session
            
        Returns:
            Dict containing response, intent, and metadata
        """
        try:
            # Step 1: Domain guard check
            if not is_job_related(message):
                return {
                    "response": get_blocked_response(),
                    "intent": "out_of_scope",
                    "success": True
                }
            
            # Step 2: Classify intent
            intent = await classify_intent(message)
            
            # Step 3: Route based on intent
            if intent == "find_jobs":
                response = await self._handle_find_jobs(message, session_history)
            elif intent == "find_leads":
                response = await self._handle_find_leads(message, session_history, user_id)
            elif intent == "find_clients":
                response = await self._handle_find_clients(message, session_history, user_id)
            elif intent in ["resume_advice", "skill_guidance", "job_info", "general_chat"]:
                response = await self._handle_conversational(message, session_history, intent)
            else:
                response = get_blocked_response()
                intent = "out_of_scope"
            
            return {
                "response": response,
                "intent": intent,
                "success": True
            }
            
        except Exception as e:
            print(f"AI Chat Service error: {str(e)}")
            return {
                "response": "I'm having trouble processing your request. Please try again.",
                "intent": "error",
                "success": False
            }
    
    async def _handle_find_jobs(self, message: str, session_history: List[ChatMessage]) -> str:
        """Handle job search requests."""
        try:
            # Extract parameters from message (simple keyword extraction)
            # In a real implementation, you'd use NLP for better extraction
            job_results = await self.job_service.search_jobs(
                query=message,
                limit=5
            )
            
            if job_results and len(job_results) > 0:
                response = f"Found {len(job_results)} relevant jobs:\n\n"
                for i, job in enumerate(job_results[:3], 1):
                    response += f"{i}. {job.get('title', 'Unknown')} at {job.get('company', 'Unknown')}\n"
                    response += f"   Location: {job.get('location', 'Not specified')}\n"
                    response += f"   {job.get('description', '')[:100]}...\n\n"
                
                response += "Would you like more details about any of these jobs or help with your resume for these positions?"
            else:
                response = "I couldn't find specific jobs matching your query. Try being more specific about job titles, skills, or locations. For example: 'software developer jobs in Bangalore' or 'data analyst positions'."
            
            return response
            
        except Exception as e:
            print(f"Job search error: {str(e)}")
            return "I'm having trouble searching for jobs right now. Please try again in a moment."
    
    async def _handle_find_leads(self, message: str, session_history: List[ChatMessage], user_id: str) -> str:
        """Handle lead finding requests."""
        try:
            # Extract city and category from message (simple extraction)
            # In a real implementation, you'd use NLP for better extraction
            message_lower = message.lower()
            
            # Default values if extraction fails
            city = "bangalore"  # Default city
            category = "restaurant"  # Default category
            radius = 5.0
            
            # Simple keyword extraction
            cities = ["bangalore", "delhi", "mumbai", "chennai", "kolkata", "hyderabad", "pune", "ahmedabad"]
            categories = ["restaurant", "jeweler", "salon", "gym", "clinic", "clothing", "bakery", "realestate", "carrepair", "hotel"]
            
            for city_name in cities:
                if city_name in message_lower:
                    city = city_name
                    break
            
            for cat in categories:
                if cat in message_lower:
                    category = cat
                    break
            
            # Extract radius if mentioned
            import re
            radius_match = re.search(r'(\d+)\s*km', message_lower)
            if radius_match:
                radius = float(radius_match.group(1))
            
            # Call the correct lead finder method
            leads = await self.lead_finder.find_and_save_leads(
                city=city,
                category=category,
                radius_km=radius,
                owner_id=user_id,
                mongo=mongo,
                limit=5
            )
            
            if leads and len(leads) > 0:
                response = f"Found {len(leads)} potential leads in {city} ({category}):\n\n"
                for i, lead in enumerate(leads[:3], 1):
                    response += f"{i}. {lead.get('name', 'Unknown')}\n"
                    response += f"   Phone: {lead.get('phone', 'Not available')}\n"
                    response += f"   Address: {lead.get('address', 'Not specified')}\n"
                    if lead.get('website'):
                        response += f"   Website: {lead.get('website')}\n"
                    response += f"   Rating: {lead.get('rating', 'N/A')}\n\n"
                
                response += f"Found these leads using Google Maps search. Would you like help crafting outreach messages for these businesses?"
            else:
                response = f"I couldn't find leads for {category} in {city}. Try a different category or city. Available categories: restaurant, jeweler, salon, gym, clinic, clothing, bakery, realestate, carrepair, hotel. Available cities: bangalore, delhi, mumbai, chennai, kolkata, hyderabad, pune, ahmedabad."
            
            return response
            
        except Exception as e:
            print(f"Lead finding error: {str(e)}")
            return "I'm having trouble finding leads right now. Please try again in a moment."
    
    async def _handle_find_clients(self, message: str, session_history: List[ChatMessage], user_id: str) -> str:
        """Handle finding existing clients/leads from database."""
        try:
            # Extract category from message
            message_lower = message.lower()
            category = None
            
            categories = ["restaurant", "jeweler", "salon", "gym", "clinic", "clothing", "bakery", "realestate", "carrepair", "hotel"]
            for cat in categories:
                if cat in message_lower:
                    category = cat
                    break
            
            # Query existing clients
            query = {"owner_id": user_id}
            if category:
                query["category"] = category
            
            cursor = mongo.clients.find(query).sort("created_at", -1).limit(10)
            clients = await cursor.to_list(length=10)
            
            if clients and len(clients) > 0:
                response = f"Found {len(clients)} existing {'leads for ' + category if category else 'leads'}:\n\n"
                for i, client in enumerate(clients[:5], 1):
                    response += f"{i}. {client.get('name', 'Unknown')}\n"
                    response += f"   Category: {client.get('category', 'Not specified')}\n"
                    response += f"   Phone: {client.get('phone', 'Not available')}\n"
                    response += f"   Address: {client.get('address', 'Not specified')}\n"
                    response += f"   Status: {client.get('status', 'lead')}\n"
                    if client.get('website'):
                        response += f"   Website: {client.get('website')}\n"
                    response += f"   Added: {client.get('created_at', 'Unknown')}\n\n"
                
                response += f"These are your existing leads in the database. Would you like help with follow-up messages or finding new leads?"
            else:
                if category:
                    response = f"You don't have any existing leads for {category}. Would you like me to find new {category} leads for you?"
                else:
                    response = "You don't have any existing leads yet. Would you like me to find some leads for you? Just tell me what category and city you're interested in."
            
            return response
            
        except Exception as e:
            print(f"Find clients error: {str(e)}")
            return "I'm having trouble retrieving your existing leads right now. Please try again in a moment."
    
    async def _handle_conversational(
        self, 
        message: str, 
        session_history: List[ChatMessage], 
        intent: str
    ) -> str:
        """Handle conversational responses with Gemini."""
        try:
            model = genai.GenerativeModel(
                model_name=settings.gemini_model,
                generation_config={
                    "temperature": settings.gemini_temperature_default,
                    "max_output_tokens": settings.gemini_max_tokens_default,
                    "top_p": 0.8,
                    "top_k": 40
                }
            )
            
            # Build conversation history
            conversation = []
            for msg in session_history[-10:]:  # Last 10 messages for context
                conversation.append(f"{msg.role.value}: {msg.content}")
            
            conversation.append(f"user: {message}")
            conversation_history_str = "\n".join(conversation)
            
            # System prompt based on intent
            system_prompts = {
                "resume_advice": "You are a resume expert. Provide specific, actionable advice for improving resumes, formatting, content, and tailoring for specific jobs.",
                "skill_guidance": "You are a career counselor. Provide guidance on skill development, learning paths, and career progression.",
                "job_info": "You are a job market expert. Provide information about job trends, salary expectations, and career opportunities.",
                "general_chat": "You are a helpful job and career assistant. Answer questions about jobs, resumes, careers, and professional development."
            }
            
            system_prompt = system_prompts.get(intent, system_prompts["general_chat"])
            
            full_prompt = f"""{system_prompt}

You are a job assistant. Only answer job, resume, career, and hiring related questions. Never go outside this domain.

Conversation history:
{conversation_history_str}

Provide a helpful, concise response to the user's latest message."""
            
            response = await model.generate_content_async(full_prompt)
            return response.text.strip()
            
        except Exception as e:
            print(f"Conversational AI error: {str(e)}")
            return "I'm having trouble generating a response right now. Please try again."


# Singleton instance
ai_chat_service = AIChatService()
