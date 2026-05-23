from pydantic import BaseModel

class ChatMessage(BaseModel):
    role: str  # "user" or "agent"
    content: str

class ChatRequest(BaseModel):
    session_id: str
    parquet_path: str
    dataset_profile: dict
    messages: list[ChatMessage]
    message: str