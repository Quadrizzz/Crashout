from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm import Gemini
from app.agent.prompts.chart_decider import CHART_DECIDER_SYSTEM_PROMPT
from app.agent.state import AgentState

llm = Gemini(model="gemini-2.5-flash").llm

class ChartDeciderOutput(BaseModel):
    reasoning: str = Field(description="Explanation for the chart generation decision")
    generate_chart: bool = Field(description="True if a chart should be generated, False otherwise")

structured_llm = llm.with_structured_output(ChartDeciderOutput)

async def run(state: AgentState) -> AgentState:
    """
    Decides whether a chart should be generated based on the user's query and the data result.
    Updates state.generate_chart.
    """
    # If the route itself didn't call for a chart, we can short-circuit
    if state.route not in ["chart", "hybrid"]:
        return state.model_copy(update={"generate_chart": False})
        
    context = f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n CONTEXT\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    context += f"Route executed: {state.route}\n"
    context += f"User Query: {state.current_user_message or state.messages[-1].content}\n"
    context += f"Interpreted Data Result: {state.interpreted_result}\n"
    
    system_message = CHART_DECIDER_SYSTEM_PROMPT + context
    
    result = await structured_llm.ainvoke([
        SystemMessage(content=system_message),
        HumanMessage(content="Evaluate whether we can/should generate a chart given this data.")
    ])
    
    return state.model_copy(update={
        "generate_chart": result.generate_chart
    })
