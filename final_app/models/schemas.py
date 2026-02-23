"""Pydantic schemas for request/response validation."""

from datetime import datetime, date
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# =============================================================================
# USER SCHEMAS
# =============================================================================
class UserSignUp(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=6)
    tenant_id: str
    department: Optional[str] = None
    role: str = "student"
    tier: str = "power"  # free, power, super


class UserSignIn(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    tenant_id: str
    department: Optional[str]
    role: str
    tier: str
    access_level: str
    created_at: datetime

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    """Response after successful authentication."""
    user: UserResponse
    message: str


# =============================================================================
# MESSAGE SCHEMAS
# =============================================================================
class MessageCreate(BaseModel):
    thread_id: str
    role: str  # user, assistant, system, tool
    content: Optional[str] = None
    tool_calls: Optional[dict[str, Any]] = None
    tool_name: Optional[str] = None


class MessageResponse(BaseModel):
    id: UUID
    thread_id: str
    user_id: Optional[UUID]
    role: str
    content: Optional[str]
    tool_calls: Optional[dict[str, Any]]
    tool_name: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# TWEET SCHEMAS
# =============================================================================
class TweetCreate(BaseModel):
    topic: str
    context_used: Optional[str] = None


class TweetResponse(BaseModel):
    id: UUID
    user_id: Optional[UUID]
    thread_id: Optional[str]
    topic: str
    draft_content: Optional[str]
    final_content: Optional[str]
    quality_score: Optional[float]
    iterations: int
    approved: bool
    approved_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# LINKEDIN POST SCHEMAS
# =============================================================================
class LinkedInPostCreate(BaseModel):
    topic: str
    style: str = "insight"  # insight, announcement, tutorial, story
    context_used: Optional[str] = None


class LinkedInPostResponse(BaseModel):
    id: UUID
    user_id: Optional[UUID]
    thread_id: Optional[str]
    topic: str
    outline: Optional[str]
    draft_content: Optional[str]
    final_content: Optional[str]
    quality_score: Optional[float]
    iterations: int
    style: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# EXPENSE SCHEMAS
# =============================================================================
class ExpenseCreate(BaseModel):
    amount: float = Field(..., gt=0)
    category: str
    description: Optional[str] = None
    expense_date: Optional[date] = None


class ExpenseResponse(BaseModel):
    id: UUID
    user_id: Optional[UUID]
    amount: float
    category: str
    description: Optional[str]
    expense_date: date
    created_at: datetime

    class Config:
        from_attributes = True


class ExpenseSummary(BaseModel):
    category: str
    total: float
    count: int


# =============================================================================
# PAPER SCHEMAS
# =============================================================================
class PaperCreate(BaseModel):
    arxiv_id: Optional[str] = None
    title: str
    authors: Optional[list[str]] = None
    abstract: Optional[str] = None


class PaperResponse(BaseModel):
    id: UUID
    arxiv_id: Optional[str]
    title: str
    authors: Optional[list[str]]
    abstract: Optional[str]
    chunk_count: int
    webpage_url: Optional[str]
    user_id: Optional[UUID]
    tenant_id: Optional[str]
    embedded_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# CHAT SCHEMAS
# =============================================================================
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    selected_sources: Optional[list[str]] = None  # List of arxiv_ids or document names to search
    tenant_id: Optional[str] = None  # For visibility filtering
    department: Optional[str] = None  # For visibility filtering


class ToolUsage(BaseModel):
    """Information about a tool that was used."""
    name: str
    args: Optional[dict[str, Any]] = None
    result: Optional[str] = None


class RAGChunk(BaseModel):
    """A retrieved RAG chunk."""
    content: str
    paper_title: Optional[str] = None
    arxiv_id: Optional[str] = None
    section: Optional[str] = None
    relevance_score: Optional[float] = None


class RAGContext(BaseModel):
    """RAG retrieval context with query and results."""
    query: str  # The exact query sent to Qdrant
    chunks: list[RAGChunk] = []


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    tool_calls: Optional[list[dict[str, Any]]] = None
    tools_used: Optional[list[ToolUsage]] = None  # All tools used in the conversation
    rag_context: Optional[RAGContext] = None  # RAG query and retrieved chunks
    requires_approval: bool = False
    approval_type: Optional[str] = None  # "tweet", "linkedin", etc.
    pending_content: Optional[str] = None
