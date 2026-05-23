import json
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm import Gemini
from app.agent.prompts import CODE_WRITER_SYSTEM_PROMPT
from app.agent.state import AgentState

llm = Gemini(model="gemini-2.5-flash").llm

class CodeWriterOutput(BaseModel):
    language: str = Field(description="The language of the code to be generated ('sql' for simple queries, 'python' otherwise)")
    code: str = Field(description="The raw, executable code in the chosen language")
    reasoning: str = Field(description="Explanation of the approach")

structured_llm = llm.with_structured_output(CodeWriterOutput)

async def run(state: AgentState) -> AgentState:
    profile_str = json.dumps(state.dataset_profile, indent=2)
    
    # Inject dynamic context
    context = f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n CONTEXT\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    context += f"Dataset Profile:\n{profile_str}\n"
    
    if state.execution_error:
        context += f"\n[PREVIOUS EXECUTION ERROR]:\n{state.execution_error}\n"
        context += f"\n[PREVIOUS CODE]:\n{state.generated_code}\n"
        context += "\nPlease fix the errors in your previous code and try again.\n"
    if state.code_error:
        context += f"\n[PREVIOUS CODE ERROR]:\n{state.code_error}\n"
        context += f"\n[PREVIOUS CODE]:\n{state.generated_code}\n"
        context += "\nPlease fix the errors in your previous code and try again.\n"
        
    # Replace {parquet_path} exactly as requested
    base_prompt = CODE_WRITER_SYSTEM_PROMPT.replace("{parquet_path}", state.parquet_path)
    system_message = base_prompt + context
    
    user_message = state.current_user_message
    if not user_message and state.messages:
        user_message = state.messages[-1].content
        
    result = await structured_llm.ainvoke([
        SystemMessage(content=system_message),
        HumanMessage(content=user_message)
    ])
    
    # Clear any previous execution errors and update the code
    return state.model_copy(update={
        "generated_code": result.code,
        "code_language": result.language,
        "execution_error": ""
    })