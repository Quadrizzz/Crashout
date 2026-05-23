import json
from pydantic import BaseModel, Field
from typing import List, Literal, Dict, Any, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm import Gemini
from app.agent.prompts.chart_generator import CHART_GENERATOR_SYSTEM_PROMPT
from app.agent.state import AgentState

llm = Gemini(model="gemini-3.1-flash-lite-preview").llm

class ChartConfigOutput(BaseModel):
    chart_type: Literal["bar", "line", "area", "pie", "scatter"] = Field(description="The optimal chart type to render")
    data: List[Dict[str, Any]] = Field(description="Array of standardized objects representing the plotted data rows")
    x_axis_key: Optional[str] = Field(description="The key in the data objects to use for the X-axis")
    y_axis_keys: Optional[List[str]] = Field(description="Array of keys in the data objects to plot on the Y-axis")
    title: Optional[str] = Field(description="A descriptive title for the chart")
    description: Optional[str] = Field(description="A brief 1-sentence subtitle describing what the chart visualizes")

structured_llm = llm.with_structured_output(ChartConfigOutput)

async def run(state: AgentState) -> AgentState:
    """
    Generates a Recharts compatible configuration JSON based on the raw execution data.
    """
    if not state.execution_result:
        return state.model_copy(update={"chart_config": None})
        
    context = f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n CONTEXT\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    context += f"User Query: {state.current_user_message or state.messages[-1].content}\n"
    context += f"Raw Data Execution Result: {state.execution_result}\n"
    
    system_message = CHART_GENERATOR_SYSTEM_PROMPT + context
    
    result = await structured_llm.ainvoke([
        SystemMessage(content=system_message),
        HumanMessage(content="Generate the strict JSON Chart Configuration for this data.")
    ])

    # after getting the LLM response
    if not result.x_axis_key and result.data:
        # infer from data keys
        keys = list(result.data[0].keys())
        result.x_axis_key = keys[0] if keys else "x"
        result.y_axis_keys = [keys[1]] if len(keys) > 1 else ["y"]

    if not result.title:
        result.title = f"{result.chart_type.capitalize()} Chart"

    if not result.description:
        result.description = f"Chart for {result.x_axis_key} and {result.y_axis_keys} using {result.chart_type}"
    
    # Dump the pydantic model directly into the state's expected dict structure
    return state.model_copy(update={
        "chart_config": result.model_dump()
    })
