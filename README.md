# Data Analysis Agent — Backend

An enterprise-ready AI data analysis engine built with **FastAPI**, **LangGraph**, and **Google Gemini**. Upload structured datasets (CSV, Excel, JSON, Parquet) and converse with an autonomous agent that generates and executes verified DuckDB/Python queries, interprets findings, and delivers interactive visual charts via Server-Sent Events (SSE).

---

## Tech Stack

- **FastAPI** — High-performance async REST API with Server-Sent Events (SSE) streaming.
- **LangGraph** — Cyclic graph orchestration with state machines and self-correcting error loops.
- **Google Gemini (3.x)** — Multi-model fallback chain (`gemini-3.8-flash` → `gemini-3.5-flash-lite` → `gemini-3.1-pro-preview`) with structured JSON outputs.
- **DuckDB & Pandas** — In-memory SQL engine and data manipulation.
- **E2B Code Interpreter** — Cloud sandboxing for secure, isolated Python execution.
- **AWS S3 & Boto3** — Cloud dataset storage with presigned URLs.
- **PostgreSQL & SQLAlchemy (Async)** — Persistent storage with connection pooling (`pool_pre_ping`, `pool_recycle`).
- **Supabase Auth** — Bearer JWT verification and automated user provisioning.
- **ReportLab** — Automated PDF report generation with data summaries and visual styling.

---

## End-to-End Chat Request Flow

The following diagram illustrates the complete lifecycle of a user prompt—from frontend dispatch through JWT authentication, LangGraph node execution, real-time SSE streaming, and database persistence:

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Frontend
    participant API as FastAPI (/api/v1/chat)
    participant DB as PostgreSQL
    participant Graph as LangGraph Engine
    participant S3 as AWS S3 Storage
    participant Gemini as Google Gemini
    participant Exec as DuckDB / E2B Sandbox

    User->>API: POST /api/v1/chat (Bearer JWT, session_id, message)
    API->>API: Verify JWT & auto-provision user
    API->>DB: Fetch Session & message history (IDOR check)
    API->>DB: Persist user message
    API->>API: Initialize AgentState & open SSE stream

    rect rgb(20, 24, 40)
    note right of Graph: LangGraph Execution Pipeline
    API->>Graph: agent.astream_events(state, version="v2")

    Graph->>Graph: Profiler: Check cached dataset profile (skip if exists)

    Graph->>Gemini: Router: Classify query (reasoning | code | chart | hybrid)
    Gemini-->>Graph: Route decision
    API-->>User: SSE: {"type": "status", "node": "router"}

    alt Route is "reasoning"
        Graph->>Gemini: Response Composer: Answer from metadata directly
    else Route is "code", "chart", or "hybrid"
        Graph->>Gemini: Code Writer: Generate DuckDB SQL or Python
        Gemini-->>Graph: Executable query / script
        API-->>User: SSE: {"type": "status", "node": "code_writer"}

        loop Execution Retry (up to 3x on failure)
            Graph->>S3: Code Executor: Load dataset (boto3 in-memory buffer)
            S3-->>Graph: Parquet bytes
            Graph->>Exec: Register 'df' in DuckDB / Run E2B Sandbox
            Exec-->>Graph: Query results / Stdout
            API-->>User: SSE: {"type": "status", "node": "code_executor"}
            
            opt On Execution Error
                Graph->>Gemini: Error Handler: Diagnose traceback
                API-->>User: SSE: {"type": "status", "node": "error_handler"}
                Graph->>Gemini: Code Writer: Refine query
            end
        end

        Graph->>Gemini: Result Interpreter: Formulate analytical insights
        Gemini-->>Graph: Interpreted statistical summary
        API-->>User: SSE: {"type": "status", "node": "result_interpreter"}

        opt Route is "chart" or "hybrid"
            Graph->>Gemini: Chart Generator: Build Recharts JSON config
            Gemini-->>Graph: Chart spec (bar, line, pie, etc.)
            Graph->>Graph: Normalize numbers & validate axis keys
            API-->>User: SSE: {"type": "status", "node": "chart_generator"}
        end

        Graph->>Gemini: Response Composer: Synthesize markdown response
        Gemini-->>Graph: Final response text
    end
    end

    API-->>User: SSE: {"type": "response", "message": "...", "chart_config": {...}}
    API->>DB: Open fresh session: Save assistant Message & AnalysisResult
    API-->>User: Close SSE stream
```

---

## Detailed Step-by-Step Execution Lifecycle

### 1. Request Dispatch & Authentication
- The frontend issues an HTTP `POST /api/v1/chat` request carrying the user prompt and `session_id`, alongside a Supabase JWT Bearer token in the `Authorization` header.
- [`app/api/routes/auth.py`](app/api/routes/auth.py) validates the token against `SUPABASE_JWT_SECRET`. If the authenticated user does not exist in the local database, an initial record is automatically provisioned into PostgreSQL.

### 2. Session Ownership & State Preparation
- [`app/api/routes/chat.py`](app/api/routes/chat.py) retrieves the active session from PostgreSQL using `selectinload(Session.messages)` to eliminate N+1 queries.
- **IDOR Protection**: The system enforces `session.user_id == current_user.id` and sources `session.parquet_path` and `session.profile` directly from verified database records rather than untrusted client payloads.
- The user's query is stored into PostgreSQL `messages`.
- An initial `AgentState` is constructed with the last 10 chronological conversation messages (optimizing token usage while preserving multi-turn context).

### 3. Server-Sent Events (SSE) Streaming Handshake
- FastAPI immediately returns a `StreamingResponse` with `media_type="text/event-stream"` so the frontend can receive instant, granular progress updates without waiting for full analysis completion.

### 4. LangGraph Agent Graph Execution

The execution graph (`app/agent/graph.py`) routes through the following nodes:

```mermaid
flowchart TD
    Start([User Chat Request]) --> Profiler[profiler.py]
    Profiler --> Router{router.py}
    
    Router -->|route == 'reasoning'| ResponseComposer[response_composer.py]
    Router -->|route in 'code', 'chart', 'hybrid'| CodeWriter[code_writer.py]
    
    CodeWriter --> CodeExecutor[code_executor.py]
    CodeExecutor --> CheckError{Success or Max Retries?}
    
    CheckError -->|Error & retries < 3| ErrorHandler[error_handler.py]
    ErrorHandler --> CodeWriter
    
    CheckError -->|Success| ResultInterpreter[result_interpreter.py]
    
    ResultInterpreter --> CheckChart{route in 'chart', 'hybrid'?}
    CheckChart -->|Yes| ChartGenerator[chart_generator.py]
    CheckChart -->|No: 'code' route| ResponseComposer
    
    ChartGenerator --> ResponseComposer
    ResponseComposer --> SaveDB[(PostgreSQL DB)]
    SaveDB --> End([Final Response Streamed])
```

#### A. `profiler` Node
- Detects whether `dataset_profile` is already populated from upload. During chat interactions, it skips expensive re-profiling in 0ms and transitions directly to `router`.

#### B. `router` Node
- Evaluates the user query against the dataset profile schema. Uses Gemini structured output to classify the request into one of four pathways:
  1. **`reasoning`**: Answerable directly from schema metadata (e.g., *"What columns exist?"*). Bypasses code generation.
  2. **`code`**: Calculation or filtering required without visualization (e.g., *"What is the exact maximum revenue?"*).
  3. **`chart`**: Explicit visualization request (e.g., *"Show a bar chart of top 10 categories"*).
  4. **`hybrid`**: Multi-dimensional comparisons, distributions, or trends requiring both computed metrics and an accompanying visualization.

#### C. `code_writer` Node
- Chooses the optimal execution language:
  - **SQL**: Standardized DuckDB query querying the in-memory view `df` directly.
  - **Python**: Executable pandas script with stdout output.
- Strips any accidental markdown code fences (` ```sql ` / ` ```python `) to ensure raw executable code.

#### D. `code_executor` Node
- **DuckDB SQL Execution**: Downloads the dataset from S3 into an in-memory buffer via authenticated `boto3` and registers it directly as table `df`. Queries run 100% in-memory in milliseconds with zero HTTP/S3 network errors.
- **Python Execution**: Runs inside an isolated E2B cloud sandbox with authenticated S3 presigned URLs.
- In case of errors, increments `retry_count` and invokes `error_handler` (up to 3 attempts).

#### E. `error_handler` Node
- Analyzes the execution traceback using Gemini, generates actionable code-fix feedback, and passes the corrected context back to `code_writer`.

#### F. `result_interpreter` Node
- Interprets raw tabular rows or numeric outputs into concise, human-readable statistical findings.

#### G. `chart_generator` Node
- Activated when the route is `chart` or `hybrid` and `execution_result` is present.
- Transforms raw execution records into a standardized Recharts JSON schema (`bar`, `line`, `area`, `pie`, `scatter`).
- **Data Normalization**: Converts string metrics (e.g., `"$1,200"`, `"45%"`) into clean JavaScript numbers to prevent Recharts axis scaling issues.
- **Dual Compatibility**: Injects both camelCase (`type`, `xKey`, `yKey`) and snake_case (`chart_type`, `x_axis_key`, `y_axis_keys`) properties for seamless frontend integration.

#### H. `response_composer` Node
- Combines the user query, dataset context, interpreted findings, and chart configuration into a polished markdown response.
- **Strict Anti-Hallucination Guardrail**: Prohibits the model from claiming a chart was generated unless `Chart Configuration Result` is non-null.

### 5. Final Event Delivery & Database Persistence
- As `response_composer` finishes, the route emits the final SSE payload:
  ```json
  data: {"type": "response", "message": "...", "chart_config": {...}}
  ```
- A dedicated async database session (`AsyncSessionLocal()`) saves:
  1. The assistant's `Message` in the `messages` table.
  2. The generated `AnalysisResult` (containing `chart_config`) linked to the message ID.

---

## Project Structure

```
app/
├── main.py                      # FastAPI application, CORS, routers & health check
├── api/
│   └── routes/
│       ├── auth.py              # GET /api/v1/auth/me & user provisioning
│       ├── upload.py            # POST /api/v1/upload (file conversion & profiling)
│       ├── chat.py              # POST /api/v1/chat (SSE streaming agent flow)
│       └── report.py            # GET /api/v1/report/{session_id}/pdf
├── agent/
│   ├── graph.py                 # LangGraph state graph & conditional edges
│   ├── state.py                 # Pydantic AgentState definition
│   ├── prompts/                 # System prompts for each agent node
│   └── nodes/
│       ├── profiler.py          # Dataset statistics computation & profiling
│       ├── router.py            # 4-way intent router (reasoning/code/chart/hybrid)
│       ├── code_writer.py       # SQL & Python code generation
│       ├── code_executor.py     # In-memory DuckDB & E2B Sandbox execution
│       ├── error_handler.py     # Automated traceback diagnosis & retry loop
│       ├── result_interpreter.py# Statistical finding translation
│       ├── chart_generator.py   # Recharts JSON configuration builder
│       └── response_composer.py # Final markdown synthesis
├── db/
│   ├── base.py                  # Async SQLAlchemy engine with pool pre-ping & recycle
│   ├── deps.py                  # DB session dependency injection
│   └── models.py                # User, Session, Message, AnalysisResult ORM models
├── llm/
│   └── gemini.py                # Gemini 3 client with automatic fallback routing
├── services/
│   ├── file_converter.py        # CSV/Excel/JSON to Parquet conversion
│   └── storage.py               # S3 bucket upload & presigned URL generator
└── models/
    └── schemas.py               # Pydantic schemas for requests & responses
```

---

## Environment Configuration

Create a `.env` file in the project root:

```ini
# Google Gemini API (Primary LLM)
GOOGLE_API_KEY=your_gemini_api_key

# Database (PostgreSQL)
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/crashout

# Supabase Authentication
SUPABASE_JWT_SECRET=your_supabase_jwt_secret

# AWS S3 Storage
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_REGION=eu-north-1
S3_BUCKET_NAME=new-crashout

# E2B Sandbox (Python Execution)
E2B_API_KEY=your_e2b_api_key

# CORS Settings (comma-separated allowed origins)
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,https://crashout-frontend.vercel.app
```

---

## Local Development

1. **Activate virtual environment & install dependencies**:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Start the FastAPI server**:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Verify API health**:
   - Health check: `http://localhost:8000/health`
   - Interactive OpenAPI documentation: `http://localhost:8000/docs`
