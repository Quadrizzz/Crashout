import json
import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel
from app.agent.state import AgentState
from app.llm import Gemini
from app.agent.prompts import PROFILER_SYSTEM_PROMPT

llm = Gemini(model="gemini-2.5-flash").llm

class ProfilerOutput(BaseModel):
    profile: dict

structured_llm = llm.with_structured_output(ProfilerOutput)

def _compute_statistics(df: pd.DataFrame) -> dict:
    quality_flags = []
    columns = {}

    for col in df.columns:
        null_count = int(df[col].isnull().sum())
        null_pct = round(null_count / len(df) * 100, 2)

        if null_pct > 20:
            quality_flags.append(f"Column '{col}' has {null_pct}% missing values")

        if pd.api.types.is_numeric_dtype(df[col]):
            columns[col] = {
                "type": "numeric",
                "min": _safe_val(df[col].min()),
                "max": _safe_val(df[col].max()),
                "mean": _safe_val(round(df[col].mean(), 4)),
                "median": _safe_val(df[col].median()),
                "std": _safe_val(round(df[col].std(), 4)),
                "null_count": null_count,
                "null_percentage": null_pct,
            }

        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            columns[col] = {
                "type": "datetime",
                "min": str(df[col].min()),
                "max": str(df[col].max()),
                "null_count": null_count,
                "null_percentage": null_pct,
            }

        else:
            top_values = df[col].value_counts().head(5).index.tolist()
            columns[col] = {
                "type": "categorical",
                "unique_count": int(df[col].nunique()),
                "top_values": [str(v) for v in top_values],
                "null_count": null_count,
                "null_percentage": null_pct,
            }

    duplicate_count = int(df.duplicated().sum())
    if duplicate_count > 0:
        quality_flags.append(f"{duplicate_count} duplicate rows detected")

    return {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": columns,
        "quality_flags": quality_flags,
        "summary": "",
    }


def _safe_val(val):
    """Convert numpy types to native Python for JSON serialization."""
    if hasattr(val, "item"):
        return val.item()
    return val

async def run(state: AgentState) -> AgentState:
    df = pd.read_parquet(state.parquet_path)
    stats = _compute_statistics(df)
    
    result = await structured_llm.ainvoke([
        SystemMessage(content=PROFILER_SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(stats, indent=2))
    ])

    print(result.profile)
    
    return state.model_copy(update={"dataset_profile": result.profile})