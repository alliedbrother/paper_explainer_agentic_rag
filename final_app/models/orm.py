"""SQLAlchemy ORM models matching the PostgreSQL schema."""

from datetime import datetime, date
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    ARRAY,
    Numeric,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class User(Base):
    """User model for RBAC."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[Optional[str]] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(50), default="student")
    tier: Mapped[str] = mapped_column(String(50), default="power")
    access_level: Mapped[str] = mapped_column(String(50), default="public")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    messages: Mapped[list["Message"]] = relationship(back_populates="user")
    tweets: Mapped[list["Tweet"]] = relationship(back_populates="user")
    linkedin_posts: Mapped[list["LinkedInPost"]] = relationship(back_populates="user")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="user")
    papers: Mapped[list["EmbeddedPaper"]] = relationship(back_populates="user")
    request_logs: Mapped[list["RequestLog"]] = relationship(back_populates="user")


class LangGraphCheckpoint(Base):
    """LangGraph state persistence."""

    __tablename__ = "langgraph_checkpoints"

    thread_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    parent_checkpoint_id: Mapped[Optional[str]] = mapped_column(String(255))
    checkpoint: Mapped[dict] = mapped_column(JSONB, nullable=False)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Message(Base):
    """Message history for conversations."""

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSONB)
    tool_name: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user: Mapped[Optional["User"]] = relationship(back_populates="messages")


class EmbeddedPaper(Base):
    """Embedded research papers metadata."""

    __tablename__ = "embedded_papers"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    arxiv_id: Mapped[Optional[str]] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    abstract: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    webpage_url: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    tenant_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    embedded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user: Mapped[Optional["User"]] = relationship(back_populates="papers")
    chunks: Mapped[list["PaperChunk"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )


class PaperChunk(Base):
    """Paper chunks metadata (vectors stored in Qdrant)."""

    __tablename__ = "paper_chunks"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    paper_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("embedded_papers.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    section_title: Mapped[Optional[str]] = mapped_column(String(255))
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    token_count: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    paper: Mapped["EmbeddedPaper"] = relationship(back_populates="chunks")


class Tweet(Base):
    """Generated tweets."""

    __tablename__ = "tweets"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    thread_id: Mapped[Optional[str]] = mapped_column(String(255))
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    context_used: Mapped[Optional[str]] = mapped_column(Text)
    draft_content: Mapped[Optional[str]] = mapped_column(Text)
    final_content: Mapped[Optional[str]] = mapped_column(String(280))
    quality_score: Mapped[Optional[float]] = mapped_column(Float)
    iterations: Mapped[int] = mapped_column(Integer, default=1)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user: Mapped[Optional["User"]] = relationship(back_populates="tweets")


class LinkedInPost(Base):
    """Generated LinkedIn posts."""

    __tablename__ = "linkedin_posts"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    thread_id: Mapped[Optional[str]] = mapped_column(String(255))
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    context_used: Mapped[Optional[str]] = mapped_column(Text)
    outline: Mapped[Optional[str]] = mapped_column(Text)
    draft_content: Mapped[Optional[str]] = mapped_column(Text)
    final_content: Mapped[Optional[str]] = mapped_column(Text)
    quality_score: Mapped[Optional[float]] = mapped_column(Float)
    iterations: Mapped[int] = mapped_column(Integer, default=1)
    style: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user: Mapped[Optional["User"]] = relationship(back_populates="linkedin_posts")


class Expense(Base):
    """User expenses."""

    __tablename__ = "expenses"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    expense_date: Mapped[date] = mapped_column(Date, default=date.today)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user: Mapped[Optional["User"]] = relationship(back_populates="expenses")


class RequestLog(Base):
    """Log of all API requests for analytics."""

    __tablename__ = "request_logs"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    thread_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., "chat", "chat_stream"
    message: Mapped[Optional[str]] = mapped_column(Text)  # User's question/message
    message_length: Mapped[Optional[int]] = mapped_column(Integer)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    department: Mapped[Optional[str]] = mapped_column(String(100))
    tier: Mapped[Optional[str]] = mapped_column(String(50))  # User's tier at request time
    status: Mapped[str] = mapped_column(String(50), default="success")  # success, rate_limited, error, queued
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer)  # Response time in milliseconds
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    rate_limited: Mapped[bool] = mapped_column(Boolean, default=False)
    queued: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship(back_populates="request_logs")
