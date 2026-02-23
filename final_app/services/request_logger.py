"""Service for logging API requests for analytics."""

import logging
import time
from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import RequestLog

logger = logging.getLogger(__name__)


async def log_request(
    db: AsyncSession,
    endpoint: str,
    message: str,
    user_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    department: Optional[str] = None,
    tier: Optional[str] = None,
    status: str = "success",
    response_time_ms: Optional[int] = None,
    tokens_used: Optional[int] = None,
    rate_limited: bool = False,
    queued: bool = False,
    error_message: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Log an API request for analytics.

    Args:
        db: Database session
        endpoint: API endpoint name (e.g., "chat_stream", "chat")
        message: User's message/question
        user_id: User UUID (optional)
        thread_id: Conversation thread ID
        tenant_id: Tenant ID for multi-tenancy
        department: User's department
        tier: User's tier at request time
        status: Request status (success, rate_limited, error, queued)
        response_time_ms: Response time in milliseconds
        tokens_used: Estimated tokens used
        rate_limited: Whether request was rate limited
        queued: Whether request was queued
        error_message: Error message if any
        ip_address: Client IP address
        user_agent: Client user agent
    """
    try:
        # Convert user_id to UUID if string
        user_uuid = None
        if user_id:
            try:
                user_uuid = UUID(user_id)
            except (ValueError, TypeError):
                pass

        log_entry = RequestLog(
            user_id=user_uuid,
            thread_id=thread_id,
            endpoint=endpoint,
            message=message[:5000] if message else None,  # Truncate long messages
            message_length=len(message) if message else 0,
            tenant_id=tenant_id,
            department=department,
            tier=tier,
            status=status,
            response_time_ms=response_time_ms,
            tokens_used=tokens_used,
            rate_limited=rate_limited,
            queued=queued,
            error_message=error_message[:1000] if error_message else None,
            ip_address=ip_address,
            user_agent=user_agent[:500] if user_agent else None,
        )

        db.add(log_entry)
        await db.commit()

    except Exception as e:
        # Don't fail the request if logging fails
        logger.warning(f"Failed to log request: {e}")
        try:
            await db.rollback()
        except Exception as rollback_error:
            logger.warning(f"Failed to rollback after logging error: {rollback_error}")


class RequestTimer:
    """Context manager for timing requests."""

    def __init__(self):
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, *args):
        self.end_time = time.time()

    @property
    def elapsed_ms(self) -> int:
        """Get elapsed time in milliseconds."""
        if self.start_time and self.end_time:
            return int((self.end_time - self.start_time) * 1000)
        elif self.start_time:
            return int((time.time() - self.start_time) * 1000)
        return 0

    def stop(self):
        """Manually stop the timer."""
        self.end_time = time.time()
