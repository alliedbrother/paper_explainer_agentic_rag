"""Retrieval service with hybrid search and reranking."""

from typing import Optional
from uuid import UUID

from ..config import get_settings
from ..tools.rag_tool import build_visibility_filter

settings = get_settings()


class RetrievalService:
    """Service for hybrid RAG retrieval."""

    def __init__(self):
        self._qdrant_client = None
        self._embedding_service = None

    @property
    def qdrant_client(self):
        """Lazy load Qdrant Cloud client.

        Requires QDRANT_URL and QDRANT_API_KEY to be set in environment.
        """
        if self._qdrant_client is None:
            from qdrant_client import QdrantClient

            if not settings.qdrant_url:
                raise ValueError("QDRANT_URL is required. Set it in your .env file.")
            if not settings.qdrant_api_key:
                raise ValueError("QDRANT_API_KEY is required. Set it in your .env file.")

            self._qdrant_client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key,
            )
        return self._qdrant_client

    @property
    def embedding_service(self):
        """Lazy load embedding service."""
        if self._embedding_service is None:
            from .embedding_service import EmbeddingService

            self._embedding_service = EmbeddingService()
        return self._embedding_service

    async def search(
        self,
        query: str,
        tenant_id: Optional[str] = None,
        department: Optional[str] = None,
        user_id: Optional[str] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """Search for relevant documents with visibility filtering.

        Args:
            query: Search query
            tenant_id: Optional tenant filter (RBAC)
            department: Optional department filter
            user_id: Optional user ID for visibility filtering
            top_k: Number of results

        Returns:
            List of relevant document chunks with metadata
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        # Generate query embedding
        query_embedding = await self.embedding_service.embed_text(query)

        # Build visibility-aware filter
        query_filter = None

        if tenant_id and department and user_id:
            # Full visibility filter
            query_filter = build_visibility_filter(tenant_id, department, user_id)
        elif tenant_id or department:
            # Fallback to simple tenant/department filter
            filter_conditions = []
            if tenant_id:
                filter_conditions.append(
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))
                )
            if department:
                filter_conditions.append(
                    FieldCondition(key="department", match=MatchValue(value=department))
                )
            query_filter = Filter(must=filter_conditions) if filter_conditions else None

        # Query Qdrant using corrected API
        results = self.qdrant_client.query_points(
            collection_name=settings.qdrant_collection,
            query=query_embedding,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )

        # Format results
        return [
            {
                "id": str(point.id),
                "content": point.payload.get("content", ""),
                "paper_id": point.payload.get("paper_id"),
                "section_title": point.payload.get("section_title"),
                "visibility": point.payload.get("visibility", "public"),
                "uploaded_by_user_id": point.payload.get("uploaded_by_user_id"),
                "score": point.score,
            }
            for point in results.points
        ]

    async def hybrid_search(
        self,
        query: str,
        tenant_id: Optional[str] = None,
        department: Optional[str] = None,
        user_id: Optional[str] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """Hybrid search combining vector and BM25.

        Args:
            query: Search query
            tenant_id: Optional tenant filter
            department: Optional department filter
            user_id: Optional user ID for visibility filtering
            top_k: Number of results

        Returns:
            Reranked results
        """
        # TODO: Implement hybrid search
        # 1. Vector search (Qdrant)
        # 2. BM25 search (PostgreSQL full-text)
        # 3. Reciprocal Rank Fusion
        # 4. Cohere reranking

        # For now, just use vector search with visibility
        return await self.search(
            query,
            tenant_id=tenant_id,
            department=department,
            user_id=user_id,
            top_k=top_k
        )
