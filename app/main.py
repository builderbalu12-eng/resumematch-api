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




from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup_event():
    await mongo.connect()

    from app.services.gemini_config_service import init_gemini_config
    await init_gemini_config()

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