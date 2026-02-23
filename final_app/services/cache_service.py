"""Semantic caching service for chat responses using Redis and OpenAI embeddings."""

import hashlib
import json
import time
import logging
from typing import Optional
from dataclasses import dataclass

import numpy as np
import redis
from langchain_openai import OpenAIEmbeddings

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached response entry."""
    question_hash: str
    question: str
    answer: str
    tenant_id: str
    department: Optional[str]
    used_rag: bool
    tools_used: Optional[list[str]]
    created_at: float
    last_accessed_at: float = 0.0  # For LRU eviction
    embedding: Optional[list[float]] = None
    ttl_seconds: int = 3600  # 1 hour default


@dataclass
class CacheLookupResult:
    """Result of a cache lookup."""
    hit: bool
    answer: Optional[str] = None
    entry: Optional[CacheEntry] = None
    reason: Optional[str] = None  # Why cache wasn't used
    similarity: Optional[float] = None  # Similarity score if semantic match


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot_product = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


class CacheService:
    """Redis-based semantic cache for chat responses.

    Uses OpenAI embeddings to find semantically similar cached responses.

    Caching rules:
    - Searches for semantically similar questions within same tenant
    - On cache hit:
      - If similarity < threshold → miss
      - If RAG was used and department doesn't match → miss
      - If RAG was not used and tenant matches → hit
      - If RAG was used and tenant + department match → hit
    """

    CACHE_PREFIX = "chat_cache"
    EMBEDDING_INDEX_PREFIX = "cache_embedding_index"

    @property
    def default_ttl(self) -> int:
        """Get default TTL from settings."""
        return settings.cache_ttl_seconds

    @property
    def similarity_threshold(self) -> float:
        """Get similarity threshold from settings."""
        return settings.cache_similarity_threshold

    @property
    def max_items_per_tenant(self) -> int:
        """Get max items per tenant from settings."""
        return settings.cache_max_items_per_tenant

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._connected = False
        self._embeddings: Optional[OpenAIEmbeddings] = None

    @property
    def redis(self) -> Optional[redis.Redis]:
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

    @property
    def embeddings(self) -> OpenAIEmbeddings:
        """Lazy embeddings model initialization."""
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings(
                model=settings.openai_embedding_model,
                openai_api_key=settings.openai_api_key,
            )
        return self._embeddings

    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        if self._redis is None:
            _ = self.redis
        return self._connected

    def _hash_question(self, question: str) -> str:
        """Create a hash of the question for cache key."""
        # Normalize: lowercase, strip whitespace
        normalized = question.lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:32]

    def _get_cache_key(self, question_hash: str, tenant_id: str) -> str:
        """Generate Redis key for cache entry."""
        return f"{self.CACHE_PREFIX}:{tenant_id}:{question_hash}"

    def _get_embedding_index_key(self, tenant_id: str) -> str:
        """Generate Redis key for tenant's embedding index."""
        return f"{self.EMBEDDING_INDEX_PREFIX}:{tenant_id}"

    def _generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for text using OpenAI."""
        try:
            return self.embeddings.embed_query(text)
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return []

    def _update_access_time(self, cache_key: str) -> None:
        """Update the last_accessed_at timestamp for LRU tracking."""
        try:
            cached_data = self.redis.get(cache_key)
            if cached_data:
                entry_data = json.loads(cached_data)
                entry_data["last_accessed_at"] = time.time()
                # Get remaining TTL and update with same TTL
                ttl = self.redis.ttl(cache_key)
                if ttl > 0:
                    self.redis.setex(cache_key, ttl, json.dumps(entry_data))
        except redis.RedisError as e:
            logger.error(f"Failed to update access time: {e}")

    def _evict_lru_if_needed(self, tenant_id: str) -> None:
        """Evict least recently used entry if tenant exceeds max items."""
        index_key = self._get_embedding_index_key(tenant_id)

        try:
            cached_hashes = self.redis.smembers(index_key)

            if len(cached_hashes) < self.max_items_per_tenant:
                return  # Under limit, no eviction needed

            # Find the LRU entry
            lru_hash = None
            lru_time = float('inf')

            for question_hash in cached_hashes:
                cache_key = self._get_cache_key(question_hash, tenant_id)
                cached_data = self.redis.get(cache_key)

                if not cached_data:
                    # Stale index entry, clean up
                    self.redis.srem(index_key, question_hash)
                    continue

                entry_data = json.loads(cached_data)
                # Use last_accessed_at if available, else created_at
                access_time = entry_data.get("last_accessed_at") or entry_data.get("created_at", 0)

                if access_time < lru_time:
                    lru_time = access_time
                    lru_hash = question_hash

            # Evict LRU entry
            if lru_hash:
                lru_cache_key = self._get_cache_key(lru_hash, tenant_id)
                self.redis.delete(lru_cache_key)
                self.redis.srem(index_key, lru_hash)
                logger.info(f"Evicted LRU cache entry for tenant {tenant_id}: {lru_hash}")

        except redis.RedisError as e:
            logger.error(f"Failed to evict LRU entry: {e}")

    def _find_similar_cached(
        self,
        query_embedding: list[float],
        tenant_id: str,
        department: Optional[str],
    ) -> tuple[Optional[CacheEntry], float]:
        """Find the most similar cached entry for a tenant.

        Returns:
            Tuple of (best matching entry, similarity score)
        """
        if not query_embedding:
            logger.warning("Empty query embedding, cannot perform semantic search")
            return None, 0.0

        index_key = self._get_embedding_index_key(tenant_id)

        try:
            # Get all cached question hashes for this tenant
            cached_hashes = self.redis.smembers(index_key)
            logger.info(f"Semantic search: Found {len(cached_hashes)} cached entries for tenant {tenant_id}")

            if not cached_hashes:
                return None, 0.0

            best_entry = None
            best_similarity = 0.0
            all_similarities = []  # For debugging

            for question_hash in cached_hashes:
                cache_key = self._get_cache_key(question_hash, tenant_id)
                cached_data = self.redis.get(cache_key)

                if not cached_data:
                    # Clean up stale index entry
                    self.redis.srem(index_key, question_hash)
                    logger.debug(f"Cleaned up stale index entry: {question_hash}")
                    continue

                entry_data = json.loads(cached_data)

                # Skip if no embedding stored
                if "embedding" not in entry_data or not entry_data["embedding"]:
                    logger.warning(f"No embedding for cached question: {entry_data.get('question', 'unknown')[:50]}")
                    continue

                # Compute similarity
                similarity = cosine_similarity(query_embedding, entry_data["embedding"])
                cached_question = entry_data.get("question", "unknown")[:50]
                all_similarities.append((cached_question, similarity))
                logger.info(f"Similarity with '{cached_question}...': {similarity:.4f}")

                # Track best match regardless of threshold for logging
                if similarity > best_similarity:
                    # Check department match if RAG was used
                    if entry_data.get("used_rag", False):
                        if entry_data.get("department") != department:
                            logger.debug(f"Skipping due to department mismatch: {entry_data.get('department')} != {department}")
                            continue

                    best_similarity = similarity
                    if similarity >= self.similarity_threshold:
                        best_entry = CacheEntry(
                            question_hash=entry_data["question_hash"],
                            question=entry_data["question"],
                            answer=entry_data["answer"],
                            tenant_id=entry_data["tenant_id"],
                            department=entry_data.get("department"),
                            used_rag=entry_data["used_rag"],
                            tools_used=entry_data.get("tools_used"),
                            created_at=entry_data["created_at"],
                            embedding=entry_data.get("embedding"),
                        )

            # Log all similarities for debugging
            if all_similarities:
                logger.info(f"All similarities: {all_similarities}")
                logger.info(f"Best similarity: {best_similarity:.4f}, threshold: {self.similarity_threshold}")

            return best_entry, best_similarity

        except (redis.RedisError, json.JSONDecodeError) as e:
            logger.error(f"Error finding similar cached entry: {e}")
            return None, 0.0

    def lookup(
        self,
        question: str,
        tenant_id: str,
        department: Optional[str] = None,
    ) -> CacheLookupResult:
        """Look up a cached response using semantic similarity.

        Args:
            question: The user's question
            tenant_id: User's tenant ID
            department: User's department (for RAG filtering)

        Returns:
            CacheLookupResult with hit status and cached answer if found
        """
        if not self.is_connected():
            return CacheLookupResult(hit=False, reason="Cache unavailable")

        # First, try exact match (faster)
        question_hash = self._hash_question(question)
        cache_key = self._get_cache_key(question_hash, tenant_id)

        try:
            cached_data = self.redis.get(cache_key)

            if cached_data:
                entry_data = json.loads(cached_data)
                entry = CacheEntry(
                    question_hash=entry_data["question_hash"],
                    question=entry_data["question"],
                    answer=entry_data["answer"],
                    tenant_id=entry_data["tenant_id"],
                    department=entry_data.get("department"),
                    used_rag=entry_data["used_rag"],
                    tools_used=entry_data.get("tools_used"),
                    created_at=entry_data["created_at"],
                )

                # Tenant must match (already in cache key, but double-check)
                if entry.tenant_id != tenant_id:
                    return CacheLookupResult(hit=False, reason="Tenant mismatch")

                # If RAG was used, department must also match
                if entry.used_rag:
                    if entry.department != department:
                        return CacheLookupResult(
                            hit=False,
                            reason=f"RAG cache requires department match (cached: {entry.department}, request: {department})"
                        )

                # Exact cache hit - update access time for LRU
                self._update_access_time(cache_key)
                logger.info(f"Exact cache hit for question: {question[:50]}...")
                return CacheLookupResult(
                    hit=True,
                    answer=entry.answer,
                    entry=entry,
                    similarity=1.0,  # Exact match
                )

            # No exact match - try semantic search
            logger.info(f"No exact match for '{question[:50]}...', trying semantic search...")
            query_embedding = self._generate_embedding(question)

            if not query_embedding:
                logger.error(f"Failed to generate query embedding for semantic search")
                return CacheLookupResult(hit=False, reason="Failed to generate embedding")

            logger.info(f"Generated query embedding ({len(query_embedding)} dims), searching for similar...")

            best_entry, similarity = self._find_similar_cached(
                query_embedding, tenant_id, department
            )

            if best_entry and similarity >= self.similarity_threshold:
                # Update access time for LRU
                hit_cache_key = self._get_cache_key(best_entry.question_hash, tenant_id)
                self._update_access_time(hit_cache_key)
                logger.info(
                    f"Semantic cache hit (similarity: {similarity:.3f}) for: {question[:50]}..."
                )
                return CacheLookupResult(
                    hit=True,
                    answer=best_entry.answer,
                    entry=best_entry,
                    similarity=similarity,
                )

            return CacheLookupResult(
                hit=False,
                reason=f"No similar cached entry (best similarity: {similarity:.3f}, threshold: {self.similarity_threshold})"
            )

        except (redis.RedisError, json.JSONDecodeError) as e:
            return CacheLookupResult(hit=False, reason=f"Cache error: {str(e)}")

    def store(
        self,
        question: str,
        answer: str,
        tenant_id: str,
        department: Optional[str],
        used_rag: bool,
        tools_used: Optional[list[str]] = None,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """Store a response in cache with embedding.

        Args:
            question: The user's question
            answer: The generated answer
            tenant_id: User's tenant ID
            department: User's department
            used_rag: Whether RAG was used to generate the answer
            tools_used: List of tool names used
            ttl_seconds: Time to live in seconds (default: 1 hour)

        Returns:
            True if stored successfully
        """
        if not self.is_connected():
            return False

        question_hash = self._hash_question(question)
        cache_key = self._get_cache_key(question_hash, tenant_id)
        index_key = self._get_embedding_index_key(tenant_id)
        ttl = ttl_seconds or self.default_ttl

        # Generate embedding for semantic search
        embedding = self._generate_embedding(question)

        if embedding:
            logger.info(f"Generated embedding ({len(embedding)} dims) for: {question[:50]}...")
        else:
            logger.warning(f"Failed to generate embedding for: {question[:50]}...")

        current_time = time.time()
        entry_data = {
            "question_hash": question_hash,
            "question": question[:500],  # Truncate for storage
            "answer": answer,
            "tenant_id": tenant_id,
            "department": department,
            "used_rag": used_rag,
            "tools_used": tools_used,
            "created_at": current_time,
            "last_accessed_at": current_time,  # For LRU tracking
            "embedding": embedding,  # Store embedding for semantic search
        }

        try:
            # Evict LRU entry if tenant is at max capacity
            self._evict_lru_if_needed(tenant_id)

            # Store the cache entry
            self.redis.setex(
                cache_key,
                ttl,
                json.dumps(entry_data),
            )

            # Add to embedding index for this tenant
            self.redis.sadd(index_key, question_hash)

            logger.info(f"Cached response for tenant {tenant_id}: {question[:50]}...")
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to store cache entry: {e}")
            return False

    def invalidate(
        self,
        question: str,
        tenant_id: str,
    ) -> bool:
        """Invalidate a cache entry.

        Args:
            question: The question to invalidate
            tenant_id: Tenant ID

        Returns:
            True if deleted successfully
        """
        if not self.is_connected():
            return False

        question_hash = self._hash_question(question)
        cache_key = self._get_cache_key(question_hash, tenant_id)
        index_key = self._get_embedding_index_key(tenant_id)

        try:
            self.redis.delete(cache_key)
            self.redis.srem(index_key, question_hash)
            return True
        except redis.RedisError:
            return False

    def get_stats(self) -> dict:
        """Get cache statistics."""
        if not self.is_connected():
            return {"status": "unavailable"}

        try:
            # Count cache keys
            keys = self.redis.keys(f"{self.CACHE_PREFIX}:*")
            index_keys = self.redis.keys(f"{self.EMBEDDING_INDEX_PREFIX}:*")

            # Count entries per tenant
            tenant_counts = {}
            for key in index_keys:
                tenant_id = key.split(":")[-1]
                count = self.redis.scard(key)
                tenant_counts[tenant_id] = count

            return {
                "status": "connected",
                "type": "semantic",
                "similarity_threshold": self.similarity_threshold,
                "max_items_per_tenant": self.max_items_per_tenant,
                "ttl_seconds": self.default_ttl,
                "entries": len(keys),
                "tenants": len(index_keys),
                "entries_per_tenant": tenant_counts,
                "prefix": self.CACHE_PREFIX,
            }
        except redis.RedisError as e:
            return {"status": "error", "error": str(e)}

    def clear_all(self, tenant_id: Optional[str] = None) -> int:
        """Clear all cache entries, optionally for a specific tenant.

        Args:
            tenant_id: If provided, only clear entries for this tenant

        Returns:
            Number of entries deleted
        """
        if not self.is_connected():
            return 0

        try:
            if tenant_id:
                pattern = f"{self.CACHE_PREFIX}:{tenant_id}:*"
                index_key = self._get_embedding_index_key(tenant_id)
            else:
                pattern = f"{self.CACHE_PREFIX}:*"
                index_key = None

            keys = self.redis.keys(pattern)
            deleted = 0

            if keys:
                deleted = self.redis.delete(*keys)

            # Clear index
            if tenant_id and index_key:
                self.redis.delete(index_key)
            elif not tenant_id:
                index_keys = self.redis.keys(f"{self.EMBEDDING_INDEX_PREFIX}:*")
                if index_keys:
                    self.redis.delete(*index_keys)

            return deleted
        except redis.RedisError:
            return 0


    def debug_entries(self, tenant_id: str) -> list[dict]:
        """Get all cache entries for a tenant with debug info."""
        if not self.is_connected():
            return []

        index_key = self._get_embedding_index_key(tenant_id)
        entries = []

        try:
            cached_hashes = self.redis.smembers(index_key)

            for question_hash in cached_hashes:
                cache_key = self._get_cache_key(question_hash, tenant_id)
                cached_data = self.redis.get(cache_key)

                if cached_data:
                    entry_data = json.loads(cached_data)
                    entries.append({
                        "question_hash": question_hash,
                        "question": entry_data.get("question", ""),
                        "has_embedding": bool(entry_data.get("embedding")),
                        "embedding_length": len(entry_data.get("embedding", [])),
                        "used_rag": entry_data.get("used_rag", False),
                        "department": entry_data.get("department"),
                        "created_at": entry_data.get("created_at"),
                        "last_accessed_at": entry_data.get("last_accessed_at"),
                        "ttl_remaining": self.redis.ttl(cache_key),
                    })

            return entries
        except redis.RedisError as e:
            logger.error(f"Error getting debug entries: {e}")
            return []

    def test_similarity(self, question: str, tenant_id: str) -> dict:
        """Test similarity of a question against all cached entries."""
        if not self.is_connected():
            return {"error": "Cache unavailable"}

        # Generate embedding for test question
        query_embedding = self._generate_embedding(question)

        if not query_embedding:
            return {"error": "Failed to generate embedding for test question"}

        index_key = self._get_embedding_index_key(tenant_id)
        results = []

        try:
            cached_hashes = self.redis.smembers(index_key)

            for question_hash in cached_hashes:
                cache_key = self._get_cache_key(question_hash, tenant_id)
                cached_data = self.redis.get(cache_key)

                if cached_data:
                    entry_data = json.loads(cached_data)
                    cached_embedding = entry_data.get("embedding", [])

                    if cached_embedding:
                        similarity = cosine_similarity(query_embedding, cached_embedding)
                        results.append({
                            "cached_question": entry_data.get("question", ""),
                            "similarity": float(round(similarity, 4)),
                            "would_match": bool(similarity >= self.similarity_threshold),
                        })

            # Sort by similarity descending
            results.sort(key=lambda x: x["similarity"], reverse=True)

            return {
                "test_question": question,
                "threshold": self.similarity_threshold,
                "results": results,
                "best_match": results[0] if results else None,
            }
        except redis.RedisError as e:
            return {"error": str(e)}


# Global instance
_cache_service: Optional[CacheService] = None


def get_cache_service() -> CacheService:
    """Get the global cache service instance."""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service
