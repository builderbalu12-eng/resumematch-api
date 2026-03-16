from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import health, auth_routes, user_routes
from app.routers import resume_routes
from app.routers import payment_routes
from app.routers import openclaw_routes
from app.routers import job_routes
from app.routers import telegram_routes
from app.services.mongo import mongo
from app.routers import client_routes  # ✅ ADD


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
app.include_router(client_routes.router, prefix="/api")  # ✅ ADD




@app.on_event("startup")
async def startup_event():
    await mongo.connect()

    # Restart previously connected user gateways
    async for sess in mongo.openclaw_sessions.find({"status": "connected"}):
        OpenClawBridge.start_gateway(sess["profile"], sess["port"])
        print(f"Restarted OpenClaw gateway → {sess['profile']} :{sess['port']}")
        
@app.on_event("shutdown")
async def shutdown_event():
    await mongo.close()


@app.get("/")
async def root():
    return {"message": "ResumeMatch API is running 🚀"}