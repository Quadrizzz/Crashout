import json
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm import Gemini
from app.agent.prompts import CODE_EVALUATOR_SYSTEM_PROMPT
from app.agent.state import AgentState

llm = Gemini(model="gemini-2.5-flash").llm

class CodeEvaluatorOutput(BaseModel):
    has_error: bool = Field(description="Whether the code has any errors or performance issues")
    error: str = Field(description="The specific error and possible solutions if an error exists. Empty if no error.")
    reasoning: str = Field(description="Explanation of the evaluation")

structured_llm = llm.with_structured_output(CodeEvaluatorOutput)

async def run(state: AgentState) -> AgentState:
    profile_str = json.dumps(state.dataset_profile, indent=2)
    
    # Inject dynamic context
    context = f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n CONTEXT\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    context += f"Dataset Profile:\n{profile_str}\n"
    context += f"Code snippet to evaluate:\n```\n{state.generated_code}\n```\n"

    language = state.code_language if state.code_language else "python"
    system_message = CODE_EVALUATOR_SYSTEM_PROMPT.replace("{language}", language) + context
    
    user_message = state.current_user_message
    if not user_message and state.messages:
        user_message = state.messages[-1].content
        
    result = await structured_llm.ainvoke([
        SystemMessage(content=system_message),
        HumanMessage(content=user_message)
    ])
    
    code_error = result.error if result.has_error else ""
    
    # Update state
    return state.model_copy(update={
        "code_error": code_error
    })
