"""Main API routes for CRUD operations."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.orm import User, Tweet, LinkedInPost, Expense, EmbeddedPaper
from ..models.schemas import (
    UserResponse,
    TweetResponse,
    LinkedInPostResponse,
    ExpenseCreate,
    ExpenseResponse,
    ExpenseSummary,
    PaperResponse,
)

router = APIRouter()


# =============================================================================
# USER ENDPOINTS
# =============================================================================
@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get user by ID."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# =============================================================================
# EXPENSE ENDPOINTS
# =============================================================================
@router.post("/expenses", response_model=ExpenseResponse)
async def create_expense(
    expense: ExpenseCreate,
    user_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Add a new expense."""
    db_expense = Expense(user_id=user_id, **expense.model_dump())
    db.add(db_expense)
    await db.flush()
    await db.refresh(db_expense)
    return db_expense


@router.get("/expenses", response_model=list[ExpenseResponse])
async def list_expenses(
    user_id: UUID = Query(...),
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List expenses for a user."""
    query = select(Expense).where(Expense.user_id == user_id)
    if category:
        query = query.where(Expense.category == category)
    query = query.order_by(Expense.expense_date.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/expenses/summary", response_model=list[ExpenseSummary])
async def expense_summary(
    user_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get expense summary by category."""
    from sqlalchemy import func

    query = (
        select(
            Expense.category,
            func.sum(Expense.amount).label("total"),
            func.count(Expense.id).label("count"),
        )
        .where(Expense.user_id == user_id)
        .group_by(Expense.category)
    )
    result = await db.execute(query)
    rows = result.all()
    return [
        ExpenseSummary(category=row.category, total=float(row.total), count=row.count)
        for row in rows
    ]


# =============================================================================
# TWEET ENDPOINTS
# =============================================================================
@router.get("/tweets", response_model=list[TweetResponse])
async def list_tweets(
    user_id: UUID = Query(...),
    approved_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """List tweets for a user."""
    query = select(Tweet).where(Tweet.user_id == user_id)
    if approved_only:
        query = query.where(Tweet.approved == True)
    query = query.order_by(Tweet.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/tweets/{tweet_id}/approve", response_model=TweetResponse)
async def approve_tweet(tweet_id: UUID, db: AsyncSession = Depends(get_db)):
    """Approve a tweet for publishing."""
    from datetime import datetime

    result = await db.execute(select(Tweet).where(Tweet.id == tweet_id))
    tweet = result.scalar_one_or_none()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")

    tweet.approved = True
    tweet.approved_at = datetime.utcnow()
    await db.flush()
    await db.refresh(tweet)
    return tweet


# =============================================================================
# LINKEDIN POST ENDPOINTS
# =============================================================================
@router.get("/linkedin-posts", response_model=list[LinkedInPostResponse])
async def list_linkedin_posts(
    user_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """List LinkedIn posts for a user."""
    query = (
        select(LinkedInPost)
        .where(LinkedInPost.user_id == user_id)
        .order_by(LinkedInPost.created_at.desc())
    )
    result = await db.execute(query)
    return result.scalars().all()


# =============================================================================
# PAPER ENDPOINTS
# =============================================================================
@router.get("/papers", response_model=list[PaperResponse])
async def list_papers(
    tenant_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List embedded papers."""
    query = select(EmbeddedPaper)
    if tenant_id:
        query = query.where(EmbeddedPaper.tenant_id == tenant_id)
    query = query.order_by(EmbeddedPaper.embedded_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/papers/{arxiv_id}", response_model=PaperResponse)
async def get_paper(arxiv_id: str, db: AsyncSession = Depends(get_db)):
    """Get paper by arXiv ID."""
    result = await db.execute(
        select(EmbeddedPaper).where(EmbeddedPaper.arxiv_id == arxiv_id)
    )
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper
