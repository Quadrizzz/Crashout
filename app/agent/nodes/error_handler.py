from langchain_core.messages import HumanMessage, SystemMessage
from app.llm import Gemini
from app.agent.prompts.error_handler import ERROR_HANDLER_SYSTEM_PROMPT
from app.agent.state import AgentState

llm = Gemini(model="gemini-2.5-flash").llm

async def run(state: AgentState) -> AgentState:
    """
    Handles execution errors caught by the code_executor.
    Interprets the crash trace using an LLM to provide actionable feedback for the code_writer.
    """
    print(f"\n[Error Handler] Execution Failed (Attempt {state.retry_count} of 3)")
    
    if not state.execution_error:
        return state
        
    context = f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n CONTEXT\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    context += f"Failed Code:\n```\n{state.generated_code}\n```\n\n"
    context += f"Raw Error Trace:\n{state.execution_error}\n"
    
    system_message = ERROR_HANDLER_SYSTEM_PROMPT + context
    
    # Analyze the error
    result = await llm.ainvoke([
        SystemMessage(content=system_message),
        HumanMessage(content="Explain what caused this execution error and how to fix it concisely.")
    ])
    
    # Prepend the LLM's explanation to the raw error so the code_writer sees it clearly
    enhanced_error = f"{result.content}\n\n[RAW TRACE]:\n{state.execution_error}"
    
    return state.model_copy(update={
        "execution_error": enhanced_error
    })
