from typing import Annotated, Any
from pydantic import BaseModel, Field
import operator


class AgentState(BaseModel):
    # Dataset context
    dataset_profile: dict = Field(default_factory=dict)
    parquet_path: str = ""

    # Conversation
    messages: Annotated[list, operator.add] = Field(default_factory=list)
    current_user_message: str = ""

    # Agent working memory
    generated_code: str = ""
    code_language: str = ""
    execution_result: Any = None
    interpreted_result: str = ""
    execution_error: str = ""
    code_error: str = ""
    retry_count: int = 0

    # Routing
    route: str = ""  # "reasoning" | "code" | "hybrid"

    # Output
    generate_chart: bool = False
    chart_config: dict | None = None
    final_response: str = ""
