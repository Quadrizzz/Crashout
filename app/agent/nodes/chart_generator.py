import json
import logging
from pydantic import BaseModel, Field
from typing import List, Literal, Dict, Any, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm import Gemini
from app.agent.prompts.chart_generator import CHART_GENERATOR_SYSTEM_PROMPT
from app.agent.state import AgentState

logger = logging.getLogger(__name__)

class ChartConfigOutput(BaseModel):
    chart_type: Literal["bar", "line", "area", "pie", "scatter"] = Field(description="The optimal chart type to render")
    data: List[Dict[str, Any]] = Field(description="Array of standardized objects representing the plotted data rows")
    x_axis_key: Optional[str] = Field(default=None, description="The key in the data objects to use for the X-axis")
    y_axis_keys: Optional[List[str]] = Field(default=None, description="Array of keys in the data objects to plot on the Y-axis")
    title: Optional[str] = Field(default=None, description="A descriptive title for the chart")
    description: Optional[str] = Field(default=None, description="A brief 1-sentence subtitle describing what the chart visualizes")


def _sanitize_number(val: Any) -> Any:
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        clean = val.replace("$", "").replace(",", "").replace("%", "").strip()
        try:
            return float(clean) if "." in clean else int(clean)
        except ValueError:
            return val
    return val


def _normalize_chart_data(data: List[Dict[str, Any]], x_key: str, y_keys: List[str]) -> List[Dict[str, Any]]:
    normalized = []
    for row in data:
        if not isinstance(row, dict):
            continue
        new_row: Dict[str, Any] = {}
        for k, v in row.items():
            if k in y_keys:
                new_row[k] = _sanitize_number(v)
            else:
                new_row[k] = v
        normalized.append(new_row)
    return normalized


async def run(state: AgentState) -> AgentState:
    """
    Generates a Recharts compatible configuration JSON based on the raw execution data.
    """
    if not state.execution_result:
        return state.model_copy(update={"chart_config": None})

    try:
        # Sample or format execution result for prompt context
        raw_result = state.execution_result
        if isinstance(raw_result, list) and len(raw_result) > 50:
            sample_result = raw_result[:50]
            raw_str = f"{json.dumps(sample_result, indent=2)}\n... (truncated to 50 rows for chart plotting)"
        elif isinstance(raw_result, (list, dict)):
            raw_str = json.dumps(raw_result, indent=2)
        else:
            raw_str = str(raw_result)

        context = f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n CONTEXT\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        context += f"User Query: {state.current_user_message or (state.messages[-1].content if state.messages else '')}\n"
        context += f"Raw Data Execution Result:\n{raw_str}\n"

        system_message = CHART_GENERATOR_SYSTEM_PROMPT + context

        structured_llm = Gemini().with_structured_output(ChartConfigOutput)
        result: ChartConfigOutput = await structured_llm.ainvoke([
            SystemMessage(content=system_message),
            HumanMessage(content="Generate the strict JSON Chart Configuration for this data.")
        ])

        print(result)

        if not result or not result.data or not isinstance(result.data, list) or len(result.data) == 0:
            print("Did not generate chart")
            return state.model_copy(update={"chart_config": None})

        # Infer & validate keys from actual data rows
        first_row = result.data[0]
        if not isinstance(first_row, dict):
            return state.model_copy(update={"chart_config": None})

        available_keys = list(first_row.keys())
        if not available_keys:
            return state.model_copy(update={"chart_config": None})

        # Resolve x_axis_key
        x_key = result.x_axis_key
        if not x_key or x_key not in available_keys:
            # Pick first non-numeric/string key or first key
            str_keys = [k for k in available_keys if isinstance(first_row[k], str)]
            x_key = str_keys[0] if str_keys else available_keys[0]

        # Resolve y_axis_keys
        y_keys = [k for k in (result.y_axis_keys or []) if k in available_keys and k != x_key]
        if not y_keys:
            # Pick remaining numeric keys or remaining keys
            remaining = [k for k in available_keys if k != x_key]
            num_keys = [k for k in remaining if isinstance(_sanitize_number(first_row[k]), (int, float))]
            y_keys = num_keys if num_keys else (remaining[:1] if remaining else [available_keys[-1]])

        # Normalize data rows to convert numerical strings to actual numbers
        cleaned_data = _normalize_chart_data(result.data, x_key, y_keys)

        title = result.title or f"{result.chart_type.capitalize()} Chart"
        description = result.description or f"Visualization for {x_key} and {', '.join(y_keys)}"
        chart_type = result.chart_type or "bar"
        primary_y_key = y_keys[0] if y_keys else "value"

        # Build fully compatible config for both frontend TypeScript types and Recharts components
        chart_dict = {
            "chart_type": chart_type,
            "type": chart_type,
            "data": cleaned_data,
            "x_axis_key": x_key,
            "xKey": x_key,
            "y_axis_keys": y_keys,
            "yKey": primary_y_key,
            "title": title,
            "description": description,
        }

        print(f"Generated chart {chart_dict}")

        return state.model_copy(update={"chart_config": chart_dict})

    except Exception as exc:
        logger.exception("Failed to generate chart configuration")
        return state.model_copy(update={"chart_config": None})

