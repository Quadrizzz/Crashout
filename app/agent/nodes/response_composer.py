import json
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm import Gemini, extract_text_content
from app.agent.prompts.response_composer import RESPONSE_COMPOSER_SYSTEM_PROMPT
from app.agent.state import AgentState

llm = Gemini().llm

async def run(state: AgentState) -> AgentState:
    profile_str = json.dumps(state.dataset_profile, indent=2)
    
    context = f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n CONTEXT\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    context += f"Dataset Profile:\n{profile_str}\n"
    
    if state.route in ["code", "hybrid", "chart"]:
        # Code was executed, let's include the result
        result_str = str(state.interpreted_result) if state.interpreted_result else "No output or execution failed."
        context += f"\nCode Execution Result:\n{result_str}\n"
        
    if state.route in ["hybrid", "chart"] and state.chart_config:
        chart_str = json.dumps(state.chart_config, indent=2)
        context += f"\nChart Configuration Result:\n{chart_str}\n"

    system_message = RESPONSE_COMPOSER_SYSTEM_PROMPT.replace("{route}", state.route) + context
    
    user_message = state.current_user_message
    if not user_message and state.messages:
        user_message = state.messages[-1].content
        
    result = await llm.ainvoke([
        SystemMessage(content=system_message),
        HumanMessage(content=user_message)
    ])
    
    return state.model_copy(update={"final_response": extract_text_content(result.content)})

