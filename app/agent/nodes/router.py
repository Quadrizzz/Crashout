import json
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from typing import Literal
from app.agent.state import AgentState
from app.llm import Gemini
from app.agent.prompts import ROUTER_SYSTEM_PROMPT

llm = Gemini(model="gemini-2.5-flash").llm

class RouterOutput(BaseModel):
    reasoning: str = Field(description="Explanation for the chosen route")
    route: Literal["reasoning", "code", "hybrid", "chart"] = Field(description="The chosen execution path")

structured_llm = llm.with_structured_output(RouterOutput)

async def run(state: AgentState) -> AgentState:
    # Inject dataset profile into the system prompt context
    profile_context = f"\n\nDataset Profile:\n{json.dumps(state.dataset_profile, indent=2)}"
    system_message = ROUTER_SYSTEM_PROMPT + profile_context
    
    result = await structured_llm.ainvoke([
        SystemMessage(content=system_message),
        HumanMessage(content=state.current_user_message or state.messages[-1].content)
    ])
    
    return state.model_copy(update={"route": result.route})
