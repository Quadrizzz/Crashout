# app/api/routes/chat.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.agent.graph import agent
from app.agent.state import AgentState
from app.models.schemas import ChatRequest
from app.db.deps import get_db
from app.db.models import User, Session, Message, AnalysisResult
from app.api.routes.auth import get_current_user
import json
import uuid

router = APIRouter()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # verify session belongs to user
    session_result = await db.execute(
        select(Session).where(
            Session.id == request.session_id,
            Session.user_id == user.id,
        )
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # save user message before streaming
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

    messages = []

    if len(request.messages) > 10:
        messages = request.messages[-10]
    else:
        messages = request.messages

    state = AgentState(
        parquet_path=request.parquet_path,
        dataset_profile=request.dataset_profile,
        messages=messages,
        current_user_message=request.message
    )

    async def stream():
        final_response = ""
        chart_config = None

        async for event in agent.astream_events(state, version="v2"):
            # stream node progress to frontend
            if event["event"] == "on_chain_start":
                node_name = event.get("name", "")
                if node_name in ("router", "code_writer", "code_evaluator", "code_executor", "result_interpreter", "chart_decider"):
                    yield f"data: {json.dumps({'type': 'progress', 'node': node_name})}\n\n"

            # emit final response when response_composer finishes
            if event["event"] == "on_chain_end" and event.get("name") == "response_composer":
                output = event.get("data", {}).get("output", {})
                final_response = output.final_response
                chart_config = output.chart_config
                yield f"data: {json.dumps({'type': 'response', 'message': final_response, 'chart_config': chart_config})}\n\n"

        # save assistant message + analysis result after stream completes
        try:
            assistant_message = Message(
                id=assistant_message_id,
                session_id=request.session_id,
                user_id=user.id,
                role="assistant",
                content=final_response,
            )
            db.add(assistant_message)
            await db.flush()

            analysis_result = AnalysisResult(
                message_id=assistant_message_id,
                chart_config=chart_config,
            )
            db.add(analysis_result)
            await db.commit()

        except Exception as e:
            await db.rollback()
            print(f"Failed to save assistant message: {e}")

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
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    messages = messages_result.scalars().all()

    response = []
    for msg in messages:
        entry = {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "chart_config": None,
        }

        if msg.role == "assistant":
            ar_result = await db.execute(
                select(AnalysisResult).where(AnalysisResult.message_id == msg.id)
            )
            ar = ar_result.scalar_one_or_none()
            if ar:
                entry["chart_config"] = ar.chart_config

        response.append(entry)

    return {"messages": response}