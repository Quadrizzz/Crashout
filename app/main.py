from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import upload, chat, report

app = FastAPI(
    title="Data Analysis Agent",
    description="Upload a dataset and chat with an AI agent to get insights.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",                        # local dev
        "https://crashout-frontend.vercel.app",         # production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api/v1", tags=["Upload"])
app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(report.router, prefix="/api/v1", tags=["Report"])


@app.get("/health")
def health():
    return {"status": "ok"}
