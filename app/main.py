from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import health
from app.services.mongo import mongo  # ← this line is missing in your current code

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
        "*"  # remove this in production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)


# MongoDB connection lifecycle
@app.on_event("startup")
async def startup_event():
    await mongo.connect()


@app.on_event("shutdown")
async def shutdown_event():
    await mongo.close()


@app.get("/")
async def root():
    return {"message": "ResumeMatch API is running 🚀"}