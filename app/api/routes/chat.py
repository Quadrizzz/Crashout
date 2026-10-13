# app/api/routes/chat.py
import json
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agent.graph import agent
from app.agent.state import AgentState
from app.models.schemas import ChatRequest
from app.db.base import AsyncSessionLocal
from app.db.deps import get_db
from app.db.models import User, Session, Message, AnalysisResult
from app.api.routes.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)

NODE_STATUS_MESSAGES = {
    "profiler": "Reading dataset schema...",
    "router": "Analyzing your question...",
    "code_writer": "Writing data query...",
    "code_executor": "Executing query on your data...",
    "error_handler": "Refining query for accuracy...",
    "result_interpreter": "Analyzing results...",
    "chart_generator": "Building interactive visualization...",
    "response_composer": "Composing insights...",
}


@router.post("/chat")
async def chat(
    request: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify session belongs to user
    session_result = await db.execute(
        select(Session).where(
            Session.id == request.session_id,
            Session.user_id == user.id,
        )
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Save user message before streaming
    user_message_id = str(uuid.uuid4())
    user_message = Message(
        id=user_message_id,
        session_id=request.session_id,
        user_id=user.id,
        role="user",
        content=request.message,
    )
    db.add(user_message)
    await db.commit()

    assistant_message_id = str(uuid.uuid4())

    # Limit message history to last 10 messages safely
    messages = request.messages[-10:] if len(request.messages) > 10 else request.messages

    # Use secure session.parquet_path from verified DB session
    state = AgentState(
        parquet_path=session.parquet_path,
        dataset_profile=request.dataset_profile,
        messages=messages,
        current_user_message=request.message,
    )

    async def stream():
        final_response = ""
        chart_config = None

        try:
            async for event in agent.astream_events(state, version="v2"):
                # Stream human-friendly status & node progress to frontend
                if event["event"] == "on_chain_start":
                    node_name = event.get("name", "")
                    status_text = NODE_STATUS_MESSAGES.get(node_name)
                    if status_text:
                        yield f"data: {json.dumps({'type': 'status', 'status': status_text, 'node': node_name})}\n\n"
                    elif node_name in ("router", "code_writer", "code_executor", "result_interpreter", "chart_generator", "response_composer"):
                        yield f"data: {json.dumps({'type': 'progress', 'node': node_name})}\n\n"

                # Emit final response when response_composer finishes
                if event["event"] == "on_chain_end" and event.get("name") == "response_composer":
                    output = event.get("data", {}).get("output", {})
                    if hasattr(output, "final_response"):
                        final_response = getattr(output, "final_response", "") or ""
                        chart_config = getattr(output, "chart_config", None)
                    elif isinstance(output, dict):
                        final_response = output.get("final_response", "")
                        chart_config = output.get("chart_config", None)
                    else:
                        final_response = str(output)
                        chart_config = None

                    yield f"data: {json.dumps({'type': 'response', 'message': final_response, 'chart_config': chart_config})}\n\n"

        except Exception as exc:
            logger.exception("Error during agent streaming execution")
            yield f"data: {json.dumps({'type': 'error', 'message': f'Analysis error: {str(exc)}'})}\n\n"
            return

        # Save assistant message + analysis result using fresh DB session
        if final_response:
            try:
                async with AsyncSessionLocal() as stream_db:
                    assistant_message = Message(
                        id=assistant_message_id,
                        session_id=request.session_id,
                        user_id=user.id,
                        role="assistant",
                        content=final_response,
                    )
                    stream_db.add(assistant_message)
                    await stream_db.flush()

                    if chart_config:
                        analysis_result = AnalysisResult(
                            message_id=assistant_message_id,
                            chart_config=chart_config,
                        )
                        stream_db.add(analysis_result)

                    await stream_db.commit()
            except Exception as e:
                logger.error(f"Failed to save assistant message: {e}")

        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user.id,
        )
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages_result = await db.execute(
        select(Message)
        .options(selectinload(Message.analysis_result))
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    messages = messages_result.scalars().all()

    response = [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "chart_config": msg.analysis_result.chart_config if msg.analysis_result else None,
        }
        for msg in messages
    ]

    return {"messages": response}