"""Content management API - approve and store tweets/LinkedIn posts."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.orm import Tweet, LinkedInPost

router = APIRouter(prefix="/content", tags=["content"])


class ContentApprovalRequest(BaseModel):
    """Request to approve generated content."""
    content_type: str  # "tweet" or "linkedin"
    content: str  # The generated content
    topic: str  # Original topic
    user_id: Optional[str] = None
    thread_id: Optional[str] = None
    quality_score: Optional[float] = None


class ContentApprovalResponse(BaseModel):
    """Response after approving content."""
    success: bool
    content_id: str
    message: str


@router.post("/approve", response_model=ContentApprovalResponse)
async def approve_content(
    request: ContentApprovalRequest,
    db: AsyncSession = Depends(get_db),
):
    """Approve and store generated content (tweet or LinkedIn post).

    This endpoint is called when user clicks "Approve" on generated content.
    It stores the content in the appropriate database table.
    """
    try:
        user_uuid = UUID(request.user_id) if request.user_id else None

        if request.content_type == "tweet":
            # Extract clean tweet content (remove quality score line if present)
            clean_content = request.content
            quality_score = request.quality_score

            # Parse quality score from content if not provided
            if "Quality Score:" in clean_content:
                parts = clean_content.split("---")
                if len(parts) > 1:
                    clean_content = parts[0].strip().strip('"')
                    try:
                        score_part = parts[1]
                        import re
                        match = re.search(r"Quality Score:\s*(\d+\.?\d*)", score_part)
                        if match:
                            quality_score = float(match.group(1))
                    except:
                        pass

            tweet = Tweet(
                user_id=user_uuid,
                thread_id=request.thread_id,
                topic=request.topic,
                final_content=clean_content[:280],  # Enforce Twitter limit
                quality_score=quality_score,
                iterations=1,
                approved=True,
                approved_at=datetime.utcnow(),
            )
            db.add(tweet)
            await db.commit()
            await db.refresh(tweet)

            return ContentApprovalResponse(
                success=True,
                content_id=str(tweet.id),
                message="Tweet approved and saved successfully!",
            )

        elif request.content_type == "linkedin":
            # Extract clean post content
            clean_content = request.content
            quality_score = request.quality_score
            iterations = 1

            # Parse quality score and iterations from content if present
            if "Quality Score:" in clean_content:
                parts = clean_content.split("---")
                if len(parts) > 1:
                    clean_content = parts[0].strip()
                    try:
                        score_part = parts[1]
                        import re
                        score_match = re.search(r"Quality Score:\s*(\d+\.?\d*)", score_part)
                        iter_match = re.search(r"Iterations:\s*(\d+)", score_part)
                        if score_match:
                            quality_score = float(score_match.group(1))
                        if iter_match:
                            iterations = int(iter_match.group(1))
                    except:
                        pass

            post = LinkedInPost(
                user_id=user_uuid,
                thread_id=request.thread_id,
                topic=request.topic,
                final_content=clean_content,
                quality_score=quality_score,
                iterations=iterations,
                style="insight",  # Default style
            )
            db.add(post)
            await db.commit()
            await db.refresh(post)

            return ContentApprovalResponse(
                success=True,
                content_id=str(post.id),
                message="LinkedIn post approved and saved successfully!",
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown content type: {request.content_type}. Must be 'tweet' or 'linkedin'.",
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save content: {str(e)}")


@router.get("/tweets")
async def list_user_tweets(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all approved tweets for a user."""
    try:
        user_uuid = UUID(user_id)
        result = await db.execute(
            select(Tweet)
            .where(Tweet.user_id == user_uuid, Tweet.approved == True)
            .order_by(Tweet.created_at.desc())
        )
        tweets = result.scalars().all()

        return {
            "tweets": [
                {
                    "id": str(t.id),
                    "content": t.final_content,
                    "topic": t.topic,
                    "quality_score": t.quality_score,
                    "created_at": t.created_at.isoformat(),
                }
                for t in tweets
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/linkedin-posts")
async def list_user_linkedin_posts(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all LinkedIn posts for a user."""
    try:
        user_uuid = UUID(user_id)
        result = await db.execute(
            select(LinkedInPost)
            .where(LinkedInPost.user_id == user_uuid)
            .order_by(LinkedInPost.created_at.desc())
        )
        posts = result.scalars().all()

        return {
            "posts": [
                {
                    "id": str(p.id),
                    "content": p.final_content,
                    "topic": p.topic,
                    "quality_score": p.quality_score,
                    "iterations": p.iterations,
                    "created_at": p.created_at.isoformat(),
                }
                for p in posts
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
