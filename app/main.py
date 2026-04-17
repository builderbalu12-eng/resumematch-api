from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import health, auth_routes, user_routes
from app.routers import resume_routes
from app.routers import payment_routes
from app.routers import openclaw_routes
from app.routers import job_routes
from app.routers import telegram_routes
from app.routers import chat_routes
from app.services.mongo import mongo
from app.routers import client_routes  # ✅ ADD
from app.routers import admin_routes
from app.routers import application_routes
from app.routers import portfolio_routes
from app.routers import interview_routes
from app.routers import github_sync_routes
from app.routers import autoapply_routes
from app.routers import settings_routes
from app.routers import job_evaluation_routes
from app.routers import star_routes
from app.routers import company_research_routes
from app.routers import outreach_routes
from app.routers import compensation_routes


app = FastAPI(
    title="ResumeMatch Pro API",
    description="Backend API for AI-powered resume tailoring Chrome extension & web app",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "deepLinking": True,
        "persistAuthorization": True,
        "displayOperationId": True,
        "defaultModelsExpandDepth": -1,
    }
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:4200",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router)
# Main auth routes (register, login, google/url) — keep /api prefix
app.include_router(auth_routes.router, prefix="/api")
# Google callback — NO prefix (so path is /auth/google/callback)
app.include_router(auth_routes.google_callback_router)
app.include_router(user_routes.router, prefix="/api")
app.include_router(resume_routes.router, prefix="/api")
app.include_router(payment_routes.router, prefix="/api")
app.include_router(openclaw_routes.router, prefix="/api")
app.include_router(telegram_routes.router, prefix="/api")
app.include_router(job_routes.router, prefix="/api")
app.include_router(chat_routes.router, prefix="/api")
app.include_router(client_routes.router, prefix="/api")  # ✅ ADD
app.include_router(admin_routes.router, prefix="/api")
app.include_router(application_routes.router, prefix="/api")
app.include_router(portfolio_routes.router, prefix="/api")
app.include_router(interview_routes.router, prefix="/api")
app.include_router(github_sync_routes.router, prefix="/api")
app.include_router(autoapply_routes.router, prefix="/api")
app.include_router(settings_routes.router, prefix="/api")
app.include_router(job_evaluation_routes.router, prefix="/api")
app.include_router(star_routes.router, prefix="/api")
app.include_router(company_research_routes.router, prefix="/api")
app.include_router(outreach_routes.router, prefix="/api")
app.include_router(compensation_routes.router, prefix="/api")




from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup_event():
    await mongo.connect()

    from app.services.gemini_config_service import init_gemini_config
    await init_gemini_config()

    from app.services.claude_config_service import init_claude_config
    await init_claude_config()

    from app.services.ai_provider_service import init_active_provider
    await init_active_provider()

    # Seed job_evaluate feature cost if not already present
    existing = await mongo.credits_on_features.find_one({"feature": "job_evaluate"})
    if not existing:
        await mongo.credits_on_features.insert_one({
            "feature": "job_evaluate",
            "display_name": "Job Evaluation (6-Axis)",
            "credits_per_unit": 1,
            "unit": "evaluation",
            "description": "AI-powered 6-axis job scoring: CV match, north star, compensation, culture, red flags, posting legitimacy",
            "is_active": True,
        })

    # Seed job_followup feature cost if not already present
    existing_followup = await mongo.credits_on_features.find_one({"feature": "job_followup"})
    if not existing_followup:
        await mongo.credits_on_features.insert_one({
            "feature": "job_followup",
            "display_name": "Follow-up Generator",
            "credits_per_unit": 1,
            "unit": "generation",
            "description": "AI-generated follow-up email and LinkedIn message draft for a tracked job application",
            "is_active": True,
        })

    # Seed company_research feature cost if not already present
    existing_cr = await mongo.credits_on_features.find_one({"feature": "company_research"})
    if not existing_cr:
        await mongo.credits_on_features.insert_one({
            "feature": "company_research",
            "display_name": "Company Research",
            "credits_per_unit": 2,
            "unit": "report",
            "description": "AI-generated 6-section pre-interview company intelligence report",
            "is_active": True,
        })

    # Seed application_insights feature cost if not already present
    existing_insights = await mongo.credits_on_features.find_one({"feature": "application_insights"})
    if not existing_insights:
        await mongo.credits_on_features.insert_one({
            "feature": "application_insights",
            "display_name": "Application Insights",
            "credits_per_unit": 1,
            "unit": "generation",
            "description": "AI-generated observations from your job application patterns",
            "is_active": True,
        })

    # Seed outreach_generate feature cost if not already present
    existing_outreach = await mongo.credits_on_features.find_one({"feature": "outreach_generate"})
    if not existing_outreach:
        await mongo.credits_on_features.insert_one({
            "feature": "outreach_generate",
            "display_name": "LinkedIn Outreach Generator",
            "credits_per_unit": 1,
            "unit": "message",
            "description": "AI-generated personalized LinkedIn connection message for a specific contact type",
            "is_active": True,
        })

    # Seed star_suggest feature cost if not already present
    existing_star = await mongo.credits_on_features.find_one({"feature": "star_suggest"})
    if not existing_star:
        await mongo.credits_on_features.insert_one({
            "feature": "star_suggest",
            "display_name": "STAR Story Suggester",
            "credits_per_unit": 1,
            "unit": "suggestion",
            "description": "AI ranks the user's STAR stories by relevance for a specific job description",
            "is_active": True,
        })

    # Seed compensation_research feature cost if not already present
    existing_comp = await mongo.credits_on_features.find_one({"feature": "compensation_research"})
    if not existing_comp:
        await mongo.credits_on_features.insert_one({
            "feature": "compensation_research",
            "display_name": "Compensation Research",
            "credits_per_unit": 2,
            "unit": "research",
            "description": "AI market rate lookup: salary range, verdict, and rationale for a given role and location",
            "is_active": True,
        })

    # Ensure TTL index exists for daily_job_feed
    from app.services.daily_job_refresh_service import ensure_ttl_index, run_daily_job_refresh
    await ensure_ttl_index()

    # Schedule daily job refresh at 6:00 AM IST
    _scheduler.add_job(
        run_daily_job_refresh,
        CronTrigger(hour=6, minute=0, timezone="Asia/Kolkata"),
        id="daily_job_refresh",
        replace_existing=True,
    )
    _scheduler.start()
    print("[Scheduler] Daily job refresh scheduled at 6:00 AM IST")


@app.on_event("shutdown")
async def shutdown_event():
    _scheduler.shutdown(wait=False)
    await mongo.close()


@app.get("/")
async def root():
    return {"message": "ResumeMatch API is running 🚀"}