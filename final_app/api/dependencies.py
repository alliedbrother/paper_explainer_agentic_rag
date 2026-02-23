"""FastAPI dependencies for API endpoints."""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.orm import User
from ..services.rate_limiter import get_rate_limiter, RateLimitResult


async def get_user_tier(
    user_id: Optional[str],
    db: AsyncSession,
) -> tuple[str, str]:
    """Get user tier from database.

    Tiers:
    - free: 25 req/min, 100K tokens/hour
    - power: 25 req/min, 100K tokens/hour (default for new users)
    - super: unlimited

    Returns:
        Tuple of (user_id, tier) - defaults to ("anonymous", "power")
    """
    if not user_id:
        return "anonymous", "power"

    try:
        user_uuid = UUID(user_id)
        result = await db.execute(select(User).where(User.id == user_uuid))
        user = result.scalar_one_or_none()

        if user:
            # Use tier directly from database
            tier = user.tier or "power"
            return str(user.id), tier
    except (ValueError, Exception):
        pass

    return user_id, "power"


class RateLimitChecker:
    """Dependency class for checking rate limits."""

    async def __call__(
        self,
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> RateLimitResult:
        """Check rate limits for the current request.

        Extracts user_id from request body or query params.
        Raises HTTPException 429 if rate limit exceeded.
        """
        rate_limiter = get_rate_limiter()

        # Try to get user_id from different sources
        user_id = None

        # Check query params
        user_id = request.query_params.get("user_id")

        # Check if body was already parsed (for POST requests)
        if not user_id and hasattr(request.state, "user_id"):
            user_id = request.state.user_id

        # Get user tier
        actual_user_id, tier = await get_user_tier(user_id, db)

        # Check request rate limit
        result = rate_limiter.check_request_limit(actual_user_id, tier)

        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "message": result.reason,
                    "limit": result.limit,
                    "reset_in_seconds": result.reset_in_seconds,
                },
                headers={
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": str(result.remaining),
                    "X-RateLimit-Reset": str(result.reset_in_seconds),
                    "Retry-After": str(result.reset_in_seconds),
                },
            )

        # Store result for adding headers later
        request.state.rate_limit = result
        request.state.user_id_for_rate_limit = actual_user_id
        request.state.user_tier = tier

        return result


# Create dependency instance
check_rate_limit = RateLimitChecker()


async def check_token_limit(
    user_id: str,
    tier: str,
) -> RateLimitResult:
    """Check if user has token budget remaining.

    Call this before making LLM requests.
    """
    rate_limiter = get_rate_limiter()
    result = rate_limiter.check_token_limit(user_id, tier)

    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Token limit exceeded",
                "message": result.reason,
                "limit": result.limit,
                "remaining": result.remaining,
                "reset_in_seconds": result.reset_in_seconds,
            },
        )

    return result


def record_token_usage(user_id: str, tokens: int, tier: str) -> None:
    """Record token usage for rate limiting.

    Call this after LLM responses.
    """
    rate_limiter = get_rate_limiter()
    rate_limiter.record_tokens(user_id, tokens, tier)
