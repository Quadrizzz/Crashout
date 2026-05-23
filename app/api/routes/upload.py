# app/api/routes/upload.py
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.file_converter import convert_to_parquet
from app.agent.graph import agent
from app.agent.state import AgentState
from app.db.deps import get_db
from app.db.models import Session, DatasetProfile
from app.api.routes.auth import get_current_user
from app.db.models import User
import uuid

router = APIRouter()


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = str(uuid.uuid4())

    # Convert to parquet
    s3Url = await convert_to_parquet(file, session_id)

    # Run profiler
    initial_state = AgentState(
        parquet_path=s3Url,
        current_user_message="__profile__"
    )
    result = await agent.ainvoke(initial_state)
    profile = result["dataset_profile"]

    # Save session to DB
    session = Session(
        id=session_id,
        user_id=user.id,
        filename=file.filename,
        parquet_path=s3Url,
    )
    db.add(session)
    await db.flush()

    # Save dataset profile to DB
    dataset_profile = DatasetProfile(
        session_id=session_id,
        row_count=profile.get("overview").get("row_count", 0),
        column_count=profile.get("overview").get("column_count", 0),
        summary=profile.get("summary", ""),
        quality_flags=profile.get("quality_flags", []),
        columns=profile.get("columns", {}),
        suggested_analysis=profile.get("suggested_analysis", [])
    )
    db.add(dataset_profile)
    await db.commit()

    return {
        "session_id": session_id,
        "profile": profile,
        "parquet_path": s3Url,
    }


@router.get("/sessions")
async def get_sessions(
    page: int = 1,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select, func
    
    # Validate page number
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be >= 1")
    
    page_size = 50
    offset = (page - 1) * page_size
    
    # Get total count
    count_result = await db.execute(
        select(func.count(Session.id)).where(Session.user_id == user.id)
    )
    total_count = count_result.scalar()
    
    # Get paginated sessions
    result = await db.execute(
        select(Session)
        .where(Session.user_id == user.id)
        .order_by(Session.created_at.desc())
        .limit(page_size)
        .offset(offset)
    )
    sessions = result.scalars().all()
    
    total_pages = (total_count + page_size - 1) // page_size  # Ceiling division

    return {
        "sessions": [
            {
                "id": s.id,
                "filename": s.filename,
                "parquet_path": s.parquet_path,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sessions
        ],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }
    }


@router.get("/sessions/{session_id}/profile")
async def get_session_profile(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    session_result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    profile_result = await db.execute(
        select(DatasetProfile).where(DatasetProfile.session_id == session_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    return {
        "session_id": session_id,
        "parquet_path": session.parquet_path,
        "filename": session.filename,
        "profile": {
            "row_count": profile.row_count,
            "column_count": profile.column_count,
            "summary": profile.summary,
            "quality_flags": profile.quality_flags,
            "columns": profile.columns,
            "suggested_analysis": profile.suggested_analysis
        },
    }