import os
import logging
from typing import Type, TypeVar
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro-preview",
]

T = TypeVar("T", bound=BaseModel)


class Gemini:
    def __init__(self, model: str = "gemini-3.8-flash", fallback_models: list[str] | None = None):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable is required.")

        self.model = model
        fallbacks = (
            fallback_models
            if fallback_models is not None
            else [m for m in DEFAULT_MODELS if m != model]
        )

        self._primary = ChatGoogleGenerativeAI(
            model=self.model,
            api_key=api_key,
            max_retries=2,
            temperature=0.2,
        )
        self._fallbacks = [
            ChatGoogleGenerativeAI(
                model=m,
                api_key=api_key,
                max_retries=2,
                temperature=0.2,
            )
            for m in fallbacks
        ]

        if self._fallbacks:
            self.llm = self._primary.with_fallbacks(self._fallbacks)
        else:
            self.llm = self._primary

    def with_structured_output(self, schema: Type[T]):
        if self._fallbacks:
            return self._primary.with_structured_output(schema).with_fallbacks([
                f.with_structured_output(schema) for f in self._fallbacks
            ])
        return self._primary.with_structured_output(schema)


def extract_text_content(content: any) -> str:
    """Normalize LangChain/Gemini AIMessage content into a plain string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
            elif hasattr(item, "text"):
                parts.append(str(getattr(item, "text")))
            else:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(content) if content is not None else ""



