from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import health, auth_routes, user_routes
from app.services.mongo import mongo

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


@app.on_event("startup")
async def startup_event():
    await mongo.connect()


@app.on_event("shutdown")
async def shutdown_event():
    await mongo.close()


@app.get("/")
async def root():
    return {"message": "ResumeMatch API is running 🚀"}