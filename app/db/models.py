from sqlalchemy import (
    Column, String, Integer, Float, Boolean,
    DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
from sqlalchemy.dialects.postgresql import UUID
import uuid

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)  # UUID
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    parquet_path = Column(String, nullable=False)  # S3 URL
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="sessions")
    dataset_profile = relationship("DatasetProfile", back_populates="session", uselist=False, cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")


class DatasetProfile(Base):
    __tablename__ = "dataset_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, unique=True)
    row_count = Column(Integer, nullable=False)
    column_count = Column(Integer, nullable=False)
    summary = Column(Text, nullable=False)
    quality_flags = Column(JSON, default=list)   # list of strings
    columns = Column(JSON, default=dict)          # full column stats dict
    suggested_analysis = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="dataset_profile")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True)  # UUID
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="messages")
    user = relationship("User", back_populates="messages")
    analysis_result = relationship("AnalysisResult", back_populates="message", uselist=False, cascade="all, delete-orphan")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True)
    chart_config = Column(JSON, nullable=True)  # None if no chart was generated
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("Message", back_populates="analysis_result")