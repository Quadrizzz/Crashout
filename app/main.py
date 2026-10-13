import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import auth, upload, chat, report

app = FastAPI(
    title="Data Analysis Agent",
    description="Upload a dataset and chat with an AI agent to get insights.",
    version="0.1.0",
)

# Read CORS origins from environment (comma-separated) or fallback to defaults
default_origins = [
    "http://localhost:3000",                        # local dev
    "http://localhost:5173",                        # Vite local dev
    "https://crashout-frontend.vercel.app",         # production
]
cors_env = os.getenv("CORS_ORIGINS", "")
allowed_origins = [origin.strip() for origin in cors_env.split(",") if origin.strip()] if cors_env else default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1", tags=["Auth"])
app.include_router(upload.router, prefix="/api/v1", tags=["Upload"])
app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(report.router, prefix="/api/v1", tags=["Report"])


@app.get("/health")
def health():
    return {"status": "ok"}
