import os
from langchain_google_genai import ChatGoogleGenerativeAI


class Gemini:
    def __init__(self, model):
        self.model = model
        self.llm = ChatGoogleGenerativeAI(model=self.model, api_key=os.getenv("GOOGLE_API_KEY"))
