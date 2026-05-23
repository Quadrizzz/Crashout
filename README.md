# Data Analysis Agent

An AI-powered data analysis agent built with LangGraph and FastAPI. Upload a dataset and chat with the agent to get insights, run analysis, and generate visualizations.

## Stack

- **FastAPI** — REST API + SSE streaming
- **LangGraph** — agent orchestration
- **LangChain Anthropic** — LLM (Claude)
- **E2B** — secure code execution sandbox
- **DuckDB + Pandas** — data processing
- **PyArrow** — Parquet conversion

## Supported File Types

CSV, TSV, Excel (.xlsx/.xls), JSON, JSONL, Parquet

All files are converted to Parquet internally on upload.

## Project Structure

```
app/
├── main.py                  # FastAPI entry point
├── api/routes/
│   ├── upload.py            # POST /api/upload
│   └── chat.py              # POST /api/chat (SSE streaming)
├── agent/
│   ├── state.py             # AgentState definition
│   ├── graph.py             # LangGraph graph wiring
│   └── nodes/
│       ├── profiler.py      # Auto-profiles dataset on upload
│       ├── router.py        # Routes to reasoning or code path
│       ├── code_writer.py   # Writes pandas/DuckDB code
│       ├── code_executor.py # Executes code in E2B sandbox
│       ├── result_interpreter.py  # Explains results in plain English
│       ├── chart_decider.py       # Decides if a chart is needed
│       ├── chart_generator.py     # Builds frontend-ready chart config
│       ├── response_composer.py   # Assembles final response
│       └── error_handler.py       # Handles code execution failures
├── services/
│   ├── file_converter.py    # File type → Parquet conversion
│   └── storage.py           # File path management
└── models/
    └── schemas.py           # Pydantic request/response models
```

## Setup

1. Clone the repo and install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy `.env` and fill in your keys:
```bash
cp .env .env.local
```

Required keys:
- `ANTHROPIC_API_KEY`
- `E2B_API_KEY`

3. Run the server:
```bash
uvicorn app.main:app --reload
```

Server runs at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

## Agent Flow

```
Upload → Profiler → (end)

Chat message → Profiler (skip if cached) → Router
    → [reasoning path] → Chart Decider → Response Composer
    → [code path]      → Code Writer → Code Executor
                            ↓ (on error, retry up to 3x)
                         Error Handler → Code Writer
                            ↓ (on success)
                         Result Interpreter → Chart Decider → Response Composer
```

## API

### POST /api/upload
Upload a file. Returns session_id, parquet_path, and dataset profile.

### POST /api/chat
Send a message. Returns a streaming SSE response with progress events and the final response.
