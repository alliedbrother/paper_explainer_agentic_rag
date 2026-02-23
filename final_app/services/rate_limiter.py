"""Rate limiting service using Redis sliding window algorithm."""

import logging
import time
from typing import Optional
from dataclasses import dataclass

import redis

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool
    remaining: int
    limit: int
    reset_in_seconds: int
    reason: Optional[str] = None


class RateLimiter:
    """Redis-based rate limiter with sliding window algorithm.

    Implements two types of limits:
    1. Requests per minute - sliding window counter
    2. Tokens per minute - sliding window sum

    User tiers:
    - free: 3 req/min, 100 tokens/min
    - power: 30 req/min, 20,000 tokens/min (default for new users)
    - super: Unlimited requests, Unlimited tokens
    """

    # Tiers with unlimited access
    UNLIMITED_TIERS = {"super"}

    def _get_tier_limits(self, tier: str) -> tuple[int, int]:
        """Get request and token limits for a tier.

        Returns:
            Tuple of (requests_per_minute, tokens_per_minute)
            Returns (-1, -1) for unlimited tiers
        """
        tier_lower = tier.lower()
        if tier_lower in self.UNLIMITED_TIERS:
            return (-1, -1)  # Unlimited
        elif tier_lower == "power":
            return (
                settings.rate_limit_requests_per_minute_power,
                settings.rate_limit_tokens_per_minute_power,
            )
        else:  # free or unknown defaults to free
            return (
                settings.rate_limit_requests_per_minute_free,
                settings.rate_limit_tokens_per_minute_free,
            )

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._connected = False

    @property
    def redis(self) -> redis.Redis:
        """Lazy Redis connection."""
        if self._redis is None:
            try:
                self._redis = redis.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    password=settings.redis_password,
                    db=settings.redis_db,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                # Test connection
                self._redis.ping()
                self._connected = True
            except redis.ConnectionError:
                self._connected = False
                # Return a dummy that will fail gracefully
                self._redis = None
        return self._redis

    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        if self._redis is None:
            try:
                _ = self.redis
            except (redis.RedisError, ConnectionError) as e:
                logger.warning(f"Redis connection check failed: {e}")
        return self._connected

    def _get_window_key(self, user_id: str, limit_type: str, window_seconds: int) -> str:
        """Generate Redis key for rate limit window."""
        window_start = int(time.time()) // window_seconds
        return f"ratelimit:{limit_type}:{user_id}:{window_start}"

    def check_request_limit(
        self,
        user_id: str,
        tier: str = "free",
    ) -> RateLimitResult:
        """Check if user can make a request (requests per minute limit).

        Args:
            user_id: Unique user identifier
            tier: User tier (free, power, super)

        Returns:
            RateLimitResult with allowed status and metadata
        """
        # Get limits for this tier
        req_limit, _ = self._get_tier_limits(tier)

        # Unlimited tier - always allow
        if req_limit == -1:
            return RateLimitResult(
                allowed=True,
                remaining=-1,
                limit=-1,
                reset_in_seconds=0,
            )

        # Check Redis connection - FAIL CLOSED for security
        if not self.is_connected():
            logger.warning("Rate limiter Redis unavailable - failing closed")
            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=req_limit,
                reset_in_seconds=60,
                reason="Rate limiting service unavailable - please try again later",
            )

        window_seconds = 60  # 1 minute window
        key = self._get_window_key(user_id, "req", window_seconds)

        try:
            # Increment counter and set expiry
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds)
            results = pipe.execute()

            current_count = results[0]
            remaining = max(0, req_limit - current_count)

            # Calculate reset time
            current_window = int(time.time()) // window_seconds
            reset_at = (current_window + 1) * window_seconds
            reset_in = reset_at - int(time.time())

            if current_count > req_limit:
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    limit=req_limit,
                    reset_in_seconds=reset_in,
                    reason="request rate limit hit",
                )

            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                limit=req_limit,
                reset_in_seconds=reset_in,
            )

        except redis.RedisError as e:
            # Fail open on Redis errors
            return RateLimitResult(
                allowed=True,
                remaining=-1,
                limit=req_limit,
                reset_in_seconds=0,
                reason=f"Rate limiter error: {str(e)}",
            )

    def check_token_limit(
        self,
        user_id: str,
        tier: str = "free",
    ) -> RateLimitResult:
        """Check if user has token budget remaining (tokens per minute limit).

        Args:
            user_id: Unique user identifier
            tier: User tier (free, power, super)

        Returns:
            RateLimitResult with allowed status and remaining tokens
        """
        # Get limits for this tier
        _, token_limit = self._get_tier_limits(tier)

        # Unlimited tier - always allow
        if token_limit == -1:
            return RateLimitResult(
                allowed=True,
                remaining=-1,
                limit=-1,
                reset_in_seconds=0,
            )

        # FAIL CLOSED for security
        if not self.is_connected():
            logger.warning("Rate limiter Redis unavailable - failing closed for token check")
            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=token_limit,
                reset_in_seconds=60,
                reason="Rate limiting service unavailable - please try again later",
            )

        window_seconds = 60  # 1 minute window
        key = self._get_window_key(user_id, "tokens", window_seconds)

        try:
            current_tokens = self.redis.get(key)
            current_tokens = int(current_tokens) if current_tokens else 0

            remaining = max(0, token_limit - current_tokens)

            # Calculate reset time
            current_window = int(time.time()) // window_seconds
            reset_at = (current_window + 1) * window_seconds
            reset_in = reset_at - int(time.time())

            if current_tokens >= token_limit:
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    limit=token_limit,
                    reset_in_seconds=reset_in,
                    reason="token rate limit hit",
                )

            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                limit=token_limit,
                reset_in_seconds=reset_in,
            )

        except redis.RedisError as e:
            return RateLimitResult(
                allowed=True,
                remaining=-1,
                limit=token_limit,
                reset_in_seconds=0,
                reason=f"Rate limiter error: {str(e)}",
            )

    def record_tokens(
        self,
        user_id: str,
        tokens_used: int,
        tier: str = "free",
    ) -> bool:
        """Record token usage for a user.

        Args:
            user_id: Unique user identifier
            tokens_used: Number of tokens consumed
            tier: User tier

        Returns:
            True if recorded successfully
        """
        # Don't track for unlimited tiers
        if tier.lower() in self.UNLIMITED_TIERS:
            return True

        if not self.is_connected():
            return False

        window_seconds = 60  # 1 minute window
        key = self._get_window_key(user_id, "tokens", window_seconds)

        try:
            pipe = self.redis.pipeline()
            pipe.incrby(key, tokens_used)
            pipe.expire(key, window_seconds)
            pipe.execute()
            return True
        except redis.RedisError:
            return False

    def get_usage_stats(self, user_id: str, tier: str = "free") -> dict:
        """Get current usage statistics for a user.

        Args:
            user_id: Unique user identifier
            tier: User tier

        Returns:
            Dict with requests and tokens usage info
        """
        # Get limits for this tier
        req_limit, token_limit = self._get_tier_limits(tier)
        is_unlimited = req_limit == -1

        if not self.is_connected():
            return {
                "tier": tier,
                "error": "Rate limiter unavailable",
            }

        try:
            # Get request count
            req_key = self._get_window_key(user_id, "req", 60)
            req_count = self.redis.get(req_key)
            req_count = int(req_count) if req_count else 0

            # Get token count (only for non-unlimited tiers)
            if is_unlimited:
                token_count = 0
                token_remaining = -1
                req_remaining = -1
            else:
                token_key = self._get_window_key(user_id, "tokens", 60)
                token_count = self.redis.get(token_key)
                token_count = int(token_count) if token_count else 0
                token_remaining = max(0, token_limit - token_count)
                req_remaining = max(0, req_limit - req_count)

            return {
                "tier": tier,
                "unlimited": is_unlimited,
                "requests": {
                    "used": req_count,
                    "limit": req_limit,
                    "remaining": req_remaining,
                    "window": "1 minute",
                },
                "tokens": {
                    "used": token_count,
                    "limit": token_limit,
                    "remaining": token_remaining,
                    "window": "1 minute",
                    "unlimited": is_unlimited,
                },
            }
        except redis.RedisError as e:
            return {
                "tier": tier,
                "error": f"Failed to get stats: {str(e)}",
            }


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


@dataclass
class GlobalRateLimitResult:
    """Result of a global rate limit check."""
    allowed: bool
    current_count: int
    limit: int
    reset_in_seconds: int
    queue_position: Optional[int] = None


@dataclass
class QueuedRequest:
    """A request waiting in the queue."""
    request_id: str
    user_id: str
    tier: str
    message: str
    thread_id: str
    selected_sources: Optional[list]
    tenant_id: Optional[str]
    department: Optional[str]
    created_at: float
    attempt: int = 1


class GlobalRateLimiter:
    """System-wide rate limiter with request queue.

    Implements:
    1. Global request limit (500 req/min for entire system)
    2. Request queue with backoff when limit exceeded
    3. SSE updates for queue position
    """

    QUEUE_KEY = "request_queue"
    PROCESSING_KEY = "request_processing"

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._connected = False

    @property
    def redis(self) -> redis.Redis:
        """Lazy Redis connection."""
        if self._redis is None:
            try:
                self._redis = redis.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    password=settings.redis_password,
                    db=settings.redis_db,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                self._redis.ping()
                self._connected = True
            except redis.ConnectionError:
                self._connected = False
                self._redis = None
        return self._redis

    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        if self._redis is None:
            try:
                _ = self.redis
            except (redis.RedisError, ConnectionError) as e:
                logger.warning(f"Global rate limiter Redis connection check failed: {e}")
        return self._connected

    def _get_global_key(self, window_seconds: int = 60) -> str:
        """Generate Redis key for global rate limit window."""
        window_start = int(time.time()) // window_seconds
        return f"ratelimit:global:{window_start}"

    def check_global_limit(self, increment: bool = True) -> GlobalRateLimitResult:
        """Check if system-wide rate limit allows a new request.

        Args:
            increment: If True, increment the counter (for actual requests)
                      If False, just check without incrementing (for queue checks)

        Returns:
            GlobalRateLimitResult with allowed status
        """
        if not self.is_connected():
            # FAIL CLOSED for security - deny requests when Redis unavailable
            logger.warning("Global rate limiter Redis unavailable - failing closed")
            return GlobalRateLimitResult(
                allowed=False,
                current_count=0,
                limit=settings.global_rate_limit_requests_per_minute,
                reset_in_seconds=60,
            )

        window_seconds = 60
        limit = settings.global_rate_limit_requests_per_minute
        key = self._get_global_key(window_seconds)

        try:
            if increment:
                # Increment and check
                pipe = self.redis.pipeline()
                pipe.incr(key)
                pipe.expire(key, window_seconds)
                results = pipe.execute()
                current_count = results[0]
            else:
                # Just check current value
                current_count = self.redis.get(key)
                current_count = int(current_count) if current_count else 0

            # Calculate reset time
            current_window = int(time.time()) // window_seconds
            reset_at = (current_window + 1) * window_seconds
            reset_in = reset_at - int(time.time())

            allowed = current_count <= limit

            return GlobalRateLimitResult(
                allowed=allowed,
                current_count=current_count,
                limit=limit,
                reset_in_seconds=reset_in,
            )

        except redis.RedisError:
            return GlobalRateLimitResult(
                allowed=True,
                current_count=0,
                limit=limit,
                reset_in_seconds=0,
            )

    def decrement_global_count(self) -> None:
        """Decrement the global counter (used when request is queued instead of processed)."""
        if not self.is_connected():
            return

        key = self._get_global_key(60)
        try:
            self.redis.decr(key)
        except redis.RedisError:
            pass

    def add_to_queue(self, request: QueuedRequest) -> int:
        """Add a request to the queue.

        Args:
            request: The request to queue

        Returns:
            Queue position (1-indexed)
        """
        if not self.is_connected():
            return -1

        try:
            import json
            request_data = json.dumps({
                "request_id": request.request_id,
                "user_id": request.user_id,
                "tier": request.tier,
                "message": request.message,
                "thread_id": request.thread_id,
                "selected_sources": request.selected_sources,
                "tenant_id": request.tenant_id,
                "department": request.department,
                "created_at": request.created_at,
                "attempt": request.attempt,
            })

            # Check queue size limit
            queue_size = self.redis.llen(self.QUEUE_KEY)
            if queue_size >= settings.global_queue_max_size:
                return -1  # Queue full

            # Add to end of queue (RPUSH)
            self.redis.rpush(self.QUEUE_KEY, request_data)

            # Return position (1-indexed)
            return queue_size + 1

        except redis.RedisError:
            return -1

    def get_queue_position(self, request_id: str) -> int:
        """Get the current position of a request in the queue.

        Returns:
            Position (1-indexed) or 0 if processing or -1 if not found
        """
        if not self.is_connected():
            return -1

        try:
            import json

            # Check if currently processing
            processing = self.redis.get(f"{self.PROCESSING_KEY}:{request_id}")
            if processing:
                return 0  # Currently being processed

            # Search in queue
            queue_items = self.redis.lrange(self.QUEUE_KEY, 0, -1)
            for i, item in enumerate(queue_items):
                data = json.loads(item)
                if data.get("request_id") == request_id:
                    return i + 1  # 1-indexed

            return -1  # Not found

        except redis.RedisError:
            return -1

    def get_next_from_queue(self) -> Optional[QueuedRequest]:
        """Get the next request from the queue.

        Returns:
            QueuedRequest or None if queue is empty
        """
        if not self.is_connected():
            return None

        try:
            import json

            # Pop from front of queue (LPOP)
            item = self.redis.lpop(self.QUEUE_KEY)
            if not item:
                return None

            data = json.loads(item)
            return QueuedRequest(
                request_id=data["request_id"],
                user_id=data["user_id"],
                tier=data["tier"],
                message=data["message"],
                thread_id=data["thread_id"],
                selected_sources=data.get("selected_sources"),
                tenant_id=data.get("tenant_id"),
                department=data.get("department"),
                created_at=data["created_at"],
                attempt=data.get("attempt", 1),
            )

        except redis.RedisError:
            return None

    def mark_processing(self, request_id: str) -> None:
        """Mark a request as currently being processed."""
        if not self.is_connected():
            return

        try:
            # Set with 5 minute TTL (in case of crash)
            self.redis.setex(f"{self.PROCESSING_KEY}:{request_id}", 300, "1")
        except redis.RedisError:
            pass

    def mark_complete(self, request_id: str) -> None:
        """Mark a request as complete."""
        if not self.is_connected():
            return

        try:
            self.redis.delete(f"{self.PROCESSING_KEY}:{request_id}")
        except redis.RedisError:
            pass

    def requeue_request(self, request: QueuedRequest) -> int:
        """Re-add a request to the front of the queue (for retry)."""
        if not self.is_connected():
            return -1

        try:
            import json
            request.attempt += 1
            request_data = json.dumps({
                "request_id": request.request_id,
                "user_id": request.user_id,
                "tier": request.tier,
                "message": request.message,
                "thread_id": request.thread_id,
                "selected_sources": request.selected_sources,
                "tenant_id": request.tenant_id,
                "department": request.department,
                "created_at": request.created_at,
                "attempt": request.attempt,
            })

            # Add to front of queue (LPUSH)
            self.redis.lpush(self.QUEUE_KEY, request_data)
            return 1

        except redis.RedisError:
            return -1

    def get_queue_size(self) -> int:
        """Get current queue size."""
        if not self.is_connected():
            return 0

        try:
            return self.redis.llen(self.QUEUE_KEY)
        except redis.RedisError:
            return 0

    def cleanup_stale_items(self, max_age_seconds: Optional[int] = None) -> int:
        """Remove stale items from the queue.

        Items older than max_age_seconds are considered stale (client disconnected).

        Args:
            max_age_seconds: Max age in seconds (defaults to global_queue_max_wait_seconds)

        Returns:
            Number of items removed
        """
        if not self.is_connected():
            return 0

        if max_age_seconds is None:
            max_age_seconds = settings.global_queue_max_wait_seconds

        try:
            import json

            current_time = time.time()
            queue_items = self.redis.lrange(self.QUEUE_KEY, 0, -1)
            removed_count = 0

            # Find and remove stale items
            for item in queue_items:
                data = json.loads(item)
                age = current_time - data.get("created_at", 0)

                if age > max_age_seconds:
                    # Remove this stale item
                    self.redis.lrem(self.QUEUE_KEY, 1, item)
                    removed_count += 1

            return removed_count

        except redis.RedisError:
            return 0

    def clear_queue(self) -> int:
        """Clear all items from the queue.

        Returns:
            Number of items removed
        """
        if not self.is_connected():
            return 0

        try:
            count = self.redis.llen(self.QUEUE_KEY)
            self.redis.delete(self.QUEUE_KEY)
            return count
        except redis.RedisError:
            return 0

    def get_queue_items(self) -> list[dict]:
        """Get all items in the queue with their details.

        Returns:
            List of queue item details
        """
        if not self.is_connected():
            return []

        try:
            import json

            current_time = time.time()
            queue_items = self.redis.lrange(self.QUEUE_KEY, 0, -1)

            items = []
            for i, item in enumerate(queue_items):
                data = json.loads(item)
                age = current_time - data.get("created_at", 0)
                items.append({
                    "position": i + 1,
                    "request_id": data.get("request_id"),
                    "user_id": data.get("user_id"),
                    "message_preview": data.get("message", "")[:50],
                    "age_seconds": round(age, 1),
                    "is_stale": age > settings.global_queue_max_wait_seconds,
                })

            return items

        except redis.RedisError:
            return []

    def calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff time with exponential increase and jitter.

        Args:
            attempt: Current attempt number (1-indexed)

        Returns:
            Seconds to wait before retry
        """
        import random

        # Exponential backoff: 1s, 2s, 4s, 8s, 16s...
        base_wait = min(2 ** (attempt - 1), 30)  # Cap at 30 seconds

        # Add jitter (0-500ms)
        jitter = random.uniform(0, 0.5)

        return base_wait + jitter

    def get_global_stats(self) -> dict:
        """Get global rate limit statistics."""
        if not self.is_connected():
            return {"error": "Redis unavailable"}

        try:
            key = self._get_global_key(60)
            current_count = self.redis.get(key)
            current_count = int(current_count) if current_count else 0
            queue_size = self.redis.llen(self.QUEUE_KEY)

            limit = settings.global_rate_limit_requests_per_minute

            # Calculate reset time
            window_seconds = 60
            current_window = int(time.time()) // window_seconds
            reset_at = (current_window + 1) * window_seconds
            reset_in = reset_at - int(time.time())

            return {
                "global_limit": {
                    "used": current_count,
                    "limit": limit,
                    "remaining": max(0, limit - current_count),
                    "reset_in_seconds": reset_in,
                },
                "queue": {
                    "size": queue_size,
                    "max_size": settings.global_queue_max_size,
                },
            }
        except redis.RedisError as e:
            return {"error": str(e)}


# Global instances
_global_rate_limiter: Optional[GlobalRateLimiter] = None


def get_global_rate_limiter() -> GlobalRateLimiter:
    """Get the global system-wide rate limiter instance."""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = GlobalRateLimiter()
    return _global_rate_limiter
