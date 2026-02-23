"""State definitions for LangGraph graphs."""

from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Main agent state."""

    messages: Annotated[list[BaseMessage], add_messages]
    user_id: Optional[str]
    tenant_id: Optional[str]
    rag_context: Optional[str]  # Pre-fetched RAG context for content generation tools


class TwitterState(TypedDict):
    """Twitter subgraph state."""

    topic: str
    context: Optional[str]  # RAG context
    draft: Optional[str]
    critique: Optional[str]
    quality_score: float
    iteration_count: int
    approved: Optional[bool]
    final_tweet: Optional[str]
    tweet_id: Optional[str]


class LinkedInState(TypedDict):
    """LinkedIn subgraph state."""

    topic: str
    context: Optional[str]  # RAG context
    style: str  # insight, announcement, tutorial, story
    outline: Optional[str]
    draft: Optional[str]
    critique: Optional[str]
    quality_score: float
    iteration_count: int
    final_post: Optional[str]
    post_id: Optional[str]


class EmbedderState(TypedDict):
    """Embedder subgraph state."""

    document_path: Optional[str]
    arxiv_id: Optional[str]
    is_arxiv: bool
    exists_in_db: bool
    paper_metadata: Optional[dict]  # title, authors, abstract
    chunks: list[dict]  # chunk content and metadata
    embedding_status: str  # pending, in_progress, completed, failed
    webpage_content: Optional[str]  # generated HTML
    s3_url: Optional[str]
    error: Optional[str]
