"""RAG retriever tool for querying embedded papers."""

import logging
import hashlib
from typing import Optional, Annotated

from langchain_core.tools import tool, InjectedToolArg
from langchain_core.runnables import RunnableConfig
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config import get_settings

logger = logging.getLogger(__name__)


def deduplicate_chunks(points: list, similarity_threshold: float = 0.95) -> list:
    """Remove duplicate or near-duplicate chunks.

    Uses content hashing for exact duplicates and simple text comparison
    for near-duplicates based on content overlap.

    Args:
        points: List of Qdrant points with payloads
        similarity_threshold: Threshold for considering chunks as duplicates (0-1)

    Returns:
        Deduplicated list of points
    """
    if not points:
        return points

    seen_hashes = set()
    seen_contents = []
    deduplicated = []

    for point in points:
        payload = point.payload or {}
        content = payload.get("content", "")

        # Check for exact duplicates using hash
        content_hash = hashlib.md5(content.encode()).hexdigest()
        if content_hash in seen_hashes:
            logger.debug(f"Skipping exact duplicate chunk")
            continue

        # Check for near-duplicates using simple text overlap
        is_duplicate = False
        content_words = set(content.lower().split())

        for seen_content in seen_contents:
            seen_words = set(seen_content.lower().split())
            if not content_words or not seen_words:
                continue

            # Calculate Jaccard similarity
            intersection = len(content_words & seen_words)
            union = len(content_words | seen_words)
            similarity = intersection / union if union > 0 else 0

            if similarity >= similarity_threshold:
                logger.debug(f"Skipping near-duplicate chunk (similarity: {similarity:.2f})")
                is_duplicate = True
                break

        if not is_duplicate:
            seen_hashes.add(content_hash)
            seen_contents.append(content)
            deduplicated.append(point)

    logger.info(f"Deduplicated {len(points)} chunks to {len(deduplicated)} unique chunks")
    return deduplicated


def rerank_with_cohere(query: str, points: list, top_k: int) -> list:
    """Rerank results using Cohere's rerank API.

    Args:
        query: The search query
        points: List of Qdrant points to rerank
        top_k: Number of results to return

    Returns:
        Reranked list of points
    """
    settings = get_settings()

    if not settings.cohere_api_key:
        logger.debug("Cohere API key not configured, skipping reranking")
        return points[:top_k]

    try:
        import cohere

        co = cohere.Client(settings.cohere_api_key)

        # Prepare documents for reranking
        documents = []
        for point in points:
            payload = point.payload or {}
            content = payload.get("content", "")
            title = payload.get("title", "")
            # Include title for better context
            doc_text = f"{title}: {content}" if title else content
            documents.append(doc_text)

        if not documents:
            return points[:top_k]

        # Call Cohere rerank API
        rerank_response = co.rerank(
            model="rerank-english-v3.0",
            query=query,
            documents=documents,
            top_n=min(top_k, len(documents)),
            return_documents=False,
        )

        # Reorder points based on reranking results
        reranked_points = []
        for result in rerank_response.results:
            idx = result.index
            if idx < len(points):
                # Update the score with rerank score
                point = points[idx]
                # Store original score and add rerank score to payload
                if point.payload:
                    point.payload["original_vector_score"] = point.score
                    point.payload["rerank_score"] = result.relevance_score
                point.score = result.relevance_score
                reranked_points.append(point)

        logger.info(f"Reranked {len(points)} chunks to top {len(reranked_points)} using Cohere")
        return reranked_points

    except ImportError:
        logger.warning("Cohere package not installed. Run: pip install cohere")
        return points[:top_k]
    except Exception as e:
        logger.warning(f"Cohere reranking failed: {e}, falling back to vector scores")
        return points[:top_k]


def build_visibility_filter(
    tenant_id: str,
    department: str,
    user_id: str
) -> Filter:
    """Build filter for document visibility.

    User can see:
    - Public docs in their tenant + department
    - Their own private docs (regardless of tenant/dept)

    Args:
        tenant_id: User's tenant ID
        department: User's department
        user_id: User's ID

    Returns:
        Qdrant Filter for visibility-based access control
    """
    return Filter(
        should=[  # OR
            # Public documents in my tenant + department
            Filter(must=[
                FieldCondition(key="visibility", match=MatchValue(value="public")),
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                FieldCondition(key="department", match=MatchValue(value=department)),
            ]),
            # My private documents (I own them)
            Filter(must=[
                FieldCondition(key="visibility", match=MatchValue(value="private")),
                FieldCondition(key="uploaded_by_user_id", match=MatchValue(value=user_id)),
            ]),
            # Legacy documents without visibility field (treat as public)
            Filter(
                must=[
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    FieldCondition(key="department", match=MatchValue(value=department)),
                ],
                must_not=[
                    # Has neither visibility=public nor visibility=private (legacy)
                    FieldCondition(key="visibility", match=MatchValue(value="public")),
                    FieldCondition(key="visibility", match=MatchValue(value="private")),
                ]
            ),
        ]
    )


def get_qdrant_client() -> QdrantClient:
    """Get Qdrant Cloud client with timeout configuration.

    Requires QDRANT_URL and QDRANT_API_KEY to be set in environment.
    """
    settings = get_settings()
    if not settings.qdrant_url:
        raise ValueError("QDRANT_URL is required. Set it in your .env file.")
    if not settings.qdrant_api_key:
        raise ValueError("QDRANT_API_KEY is required. Set it in your .env file.")

    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=settings.qdrant_timeout,  # Add timeout
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((TimeoutError, ConnectionError)),
    reraise=True,
)
def get_embedding(text: str) -> list[float]:
    """Generate embedding using OpenAI with automatic retry.

    Retries up to 3 times with exponential backoff on timeout/connection errors.
    """
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout,
        max_retries=settings.openai_max_retries,
    )
    response = client.embeddings.create(
        model=settings.openai_embedding_model,
        input=text,
    )
    return response.data[0].embedding


@tool
def rag_retriever(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg],
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    department: Optional[str] = None,
    top_k: int = 5,
    use_reranking: bool = True,
) -> str:
    """Retrieve relevant context from embedded research papers.

    Use this tool FIRST when generating content about research papers,
    before calling twitter_generator or linkedin_generator.

    Features:
    - Retrieves 3x top_k chunks initially for better coverage
    - Deduplicates similar/identical chunks
    - Optionally reranks using Cohere for improved relevance
    - Returns top_k most relevant unique chunks

    Args:
        query: Search query (e.g., "attention mechanism in transformers")
        config: Injected config containing selected_sources
        user_id: Optional user ID for access control
        tenant_id: Optional tenant ID for multi-tenant filtering
        department: Optional department for access control
        top_k: Number of relevant chunks to retrieve (default: 5)
        use_reranking: Whether to use Cohere reranking if available (default: True)

    Returns:
        Relevant context from embedded papers with citations
    """
    settings = get_settings()

    # Get selected_sources and user context from config
    configurable = config.get("configurable", {}) if config else {}
    selected_sources = configurable.get("selected_sources", None)
    # Override with config values if available
    user_id = user_id or configurable.get("user_id")
    tenant_id = tenant_id or configurable.get("tenant_id")
    department = department or configurable.get("department")

    try:
        client = get_qdrant_client()

        # Check if collection exists
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]

        if settings.qdrant_collection not in collection_names:
            return (
                f"No papers embedded yet. The '{settings.qdrant_collection}' collection "
                "does not exist. Please embed documents first using the document_embedder tool."
            )

        # Generate query embedding
        query_embedding = get_embedding(query)

        # Build visibility-aware filter
        query_filter = None

        if tenant_id and department and user_id:
            # Full visibility filter with all required fields
            visibility_filter = build_visibility_filter(tenant_id, department, user_id)

            # Add selected sources filter if present
            if selected_sources and len(selected_sources) > 0:
                source_filter = Filter(
                    should=[
                        FieldCondition(key="arxiv_id", match=MatchAny(any=selected_sources)),
                        FieldCondition(key="document_name", match=MatchAny(any=selected_sources)),
                    ]
                )
                query_filter = Filter(must=[visibility_filter, source_filter])
            else:
                query_filter = visibility_filter
        elif tenant_id:
            # Fallback: just tenant filter for backwards compatibility
            filter_conditions = [
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))
            ]
            if selected_sources and len(selected_sources) > 0:
                filter_conditions.append(
                    FieldCondition(key="arxiv_id", match=MatchAny(any=selected_sources))
                )
            query_filter = Filter(must=filter_conditions)
        elif selected_sources and len(selected_sources) > 0:
            # Only source filter
            query_filter = Filter(
                should=[
                    FieldCondition(key="arxiv_id", match=MatchAny(any=selected_sources)),
                    FieldCondition(key="document_name", match=MatchAny(any=selected_sources)),
                ]
            )

        # Query Qdrant - fetch 3x top_k for better deduplication coverage
        initial_limit = top_k * 3
        results = client.query_points(
            collection_name=settings.qdrant_collection,
            query=query_embedding,
            query_filter=query_filter,
            limit=initial_limit,
            with_payload=True,
        )

        # Check if we have results
        if not results.points:
            if selected_sources and len(selected_sources) > 0:
                # User selected specific sources but nothing found
                source_names = ", ".join(selected_sources[:3])
                if len(selected_sources) > 3:
                    source_names += f" and {len(selected_sources) - 3} more"
                return (
                    f"No information related to your question was found in the sources you selected "
                    f"({source_names}). Try selecting different papers or broadening your search."
                )
            else:
                return (
                    f"No relevant documents found for query: '{query}'\n"
                    "Try a different search term or embed more papers."
                )

        # Step 1: Deduplicate chunks
        unique_points = deduplicate_chunks(results.points, similarity_threshold=0.85)

        # Step 2: Rerank if enabled and Cohere is available
        if use_reranking:
            final_points = rerank_with_cohere(query, unique_points, top_k)
        else:
            final_points = unique_points[:top_k]

        logger.info(f"RAG retrieval: {len(results.points)} initial -> {len(unique_points)} deduplicated -> {len(final_points)} final")

        # Format results
        context_parts = [f"**Retrieved Context for:** '{query}'\n"]

        for i, point in enumerate(final_points, 1):
            payload = point.payload or {}
            content = payload.get("content", "No content")
            paper_title = payload.get("title", "Unknown Paper")
            section = payload.get("section_title", "")
            arxiv_id = payload.get("arxiv_id", "")
            document_name = payload.get("document_name", "")
            score = point.score

            # Use document name if no paper title
            display_title = paper_title if paper_title != "Unknown Paper" else document_name

            context_parts.append(f"---\n**[{i}] {display_title}**")
            if arxiv_id:
                context_parts.append(f"arXiv: {arxiv_id}")
            if section:
                context_parts.append(f"Section: {section}")

            # Show rerank score if available, otherwise vector score
            rerank_score = payload.get("rerank_score")
            if rerank_score is not None:
                original_score = payload.get("original_vector_score", 0)
                context_parts.append(f"Relevance: {rerank_score:.2f} (reranked from {original_score:.2f})\n")
            else:
                context_parts.append(f"Relevance: {score:.2f}\n")

            context_parts.append(content[:500] + "..." if len(content) > 500 else content)
            context_parts.append("")

        context_parts.append("---\n*Use this context to generate accurate content.*")

        return "\n".join(context_parts)

    except Exception as e:
        error_msg = str(e)
        if "Connection refused" in error_msg:
            return (
                "Qdrant vector database is not running. "
                "Please start Qdrant using: docker-compose up -d qdrant\n\n"
                "For now, I can help with other tasks that don't require RAG."
            )
        return f"RAG retrieval error: {error_msg}"
