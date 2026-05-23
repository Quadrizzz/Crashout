from langchain_core.messages import HumanMessage, SystemMessage
from app.llm import Gemini
from app.agent.prompts.result_interpreter import RESULT_INTERPRETER_SYSTEM_PROMPT
from app.agent.state import AgentState

llm = Gemini(model="gemini-2.5-flash").llm

async def run(state: AgentState) -> AgentState:
    """
    Takes the raw execution output from the code executor and interprets it into a concise,
    human-readable finding.
    """
    if not state.execution_result:
        return state.model_copy(update={"interpreted_result": "No output or execution failed."})
        
    context = f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n CONTEXT\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    context += f"User Query:\n{state.current_user_message or state.messages[-1].content}\n\n"
    context += f"Raw Code Execution Result:\n{state.execution_result}\n"
    
    system_message = RESULT_INTERPRETER_SYSTEM_PROMPT + context
    
    result = await llm.ainvoke([
        SystemMessage(content=system_message),
        HumanMessage(content="Explain explicitly what the Raw Code Execution findings show to answer my query.")
    ])
    
    return state.model_copy(update={
        "interpreted_result": result.content
    })
