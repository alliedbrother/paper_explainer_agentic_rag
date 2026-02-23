"""Agent service for orchestrating LangGraph agent with PostgreSQL persistence."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.schemas import ChatResponse, ToolUsage, RAGChunk, RAGContext
from ..models.orm import Message, Tweet, LinkedInPost
from .progress_tracker import set_session_context, get_progress_tracker

settings = get_settings()
logger = logging.getLogger(__name__)

# Thread pool for running synchronous agent in background
_executor = ThreadPoolExecutor(max_workers=4)

# Module-level singletons for checkpointer and agent
# This ensures conversation history persists across requests in PostgreSQL
_global_checkpointer = None
_global_checkpointer_context = None  # Keep context manager reference
_global_agent = None
_checkpointer_initialized = False


def _get_global_checkpointer():
    """Get or create the global PostgreSQL checkpointer singleton.

    Uses PostgresSaver for persistent conversation history across server restarts.
    Raises an error if PostgreSQL connection fails (no fallback).
    """
    global _global_checkpointer, _global_checkpointer_context, _checkpointer_initialized

    if _global_checkpointer is None:
        from langgraph.checkpoint.postgres import PostgresSaver

        # Create context manager and enter it
        connection_string = settings.postgres_url
        _global_checkpointer_context = PostgresSaver.from_conn_string(connection_string)
        _global_checkpointer = _global_checkpointer_context.__enter__()

        # Setup tables if not already done
        if not _checkpointer_initialized:
            _global_checkpointer.setup()
            _checkpointer_initialized = True
            print("PostgresSaver initialized successfully - conversations will persist in PostgreSQL")

    return _global_checkpointer


def _get_global_agent():
    """Get or create the global agent singleton."""
    global _global_agent
    if _global_agent is None:
        from ..graphs.main_graph import build_main_agent
        checkpointer = _get_global_checkpointer()
        _global_agent = build_main_agent(checkpointer=checkpointer)
    return _global_agent


class AgentService:
    """Service for managing agent interactions with LangGraph."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_checkpointer(self):
        """Get the global checkpointer singleton."""
        return _get_global_checkpointer()

    def _get_agent(self):
        """Get the global agent singleton."""
        return _get_global_agent()

    def _is_tool_specific_query(self, query: str) -> bool:
        """Check if query is specifically for calculator or expense tools.

        These queries should bypass RAG and go directly to the appropriate tool.
        """
        query_lower = query.lower()

        # Calculator patterns
        calc_patterns = [
            "calculate", "compute", "what is", "how much is",
            "multiply", "divide", "add", "subtract", "sum of",
            "square root", "sqrt", "power of", "factorial",
            "+", "-", "*", "/", "^", "=",
        ]

        # Check for math expressions (numbers with operators)
        import re
        math_expr = re.search(r'\d+\s*[\+\-\*\/\^]\s*\d+', query)
        if math_expr:
            return True

        # Expense patterns
        expense_patterns = [
            "add expense", "log expense", "record expense", "spent",
            "expense of", "paid for", "my expenses", "list expenses",
            "show expenses", "expense summary", "how much did i spend",
            "total expenses", "expense report",
        ]

        # Check calculator patterns (but only if it looks like a pure math question)
        for pattern in calc_patterns:
            if pattern in query_lower:
                # Make sure it's actually a math question, not a research question
                # containing math terms
                if any(word in query_lower for word in ["paper", "research", "study", "article", "document"]):
                    return False
                # Check if it has numbers - likely a calculation
                if re.search(r'\d', query):
                    return True

        # Check expense patterns
        for pattern in expense_patterns:
            if pattern in query_lower:
                return True

        return False

    def _references_selected_documents(self, message: str) -> bool:
        """Check if user explicitly references selected documents.

        When user says things like "use the selected document" or "from this paper",
        they want content FROM the documents, not semantic search ABOUT a topic.
        """
        message_lower = message.lower()

        patterns = [
            "selected document",
            "selected paper",
            "selected source",
            "selected file",
            "this paper",
            "this document",
            "these papers",
            "these documents",
            "the document",
            "the paper",
            "the selected",
            "from the paper",
            "from the document",
            "using the document",
            "using the paper",
            "based on the document",
            "based on the paper",
        ]

        return any(pattern in message_lower for pattern in patterns)

    def _fetch_top_chunks_from_sources(
        self,
        selected_sources: list[str],
        tenant_id: Optional[str] = None,
        department: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 5,
    ) -> tuple[str, list]:
        """Fetch top chunks from selected sources WITHOUT semantic filtering.

        Used when user explicitly references selected documents (e.g., "generate
        post from the selected document") - we want the best content from those
        docs regardless of query similarity.

        Args:
            selected_sources: List of arxiv_ids or document names
            tenant_id: User's tenant ID for visibility filtering
            department: User's department for visibility filtering
            user_id: User's ID for visibility filtering
            limit: Number of chunks to return

        Returns:
            Tuple of (rag_result_text, rag_chunks)
        """
        from ..tools.rag_tool import get_qdrant_client, build_visibility_filter
        from qdrant_client.models import Filter, FieldCondition, MatchAny

        settings = get_settings()

        try:
            client = get_qdrant_client()

            # Build source filter
            source_filter = Filter(
                should=[
                    FieldCondition(key="arxiv_id", match=MatchAny(any=selected_sources)),
                    FieldCondition(key="document_name", match=MatchAny(any=selected_sources)),
                ]
            )

            # Combine with visibility filter if available
            if tenant_id and department and user_id:
                visibility_filter = build_visibility_filter(tenant_id, department, user_id)
                query_filter = Filter(must=[visibility_filter, source_filter])
            else:
                query_filter = source_filter

            # Scroll through points from selected sources (no vector search)
            # This gets chunks directly from the documents
            results, _ = client.scroll(
                collection_name=settings.qdrant_collection,
                scroll_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )

            if not results:
                return None, []

            # Format results
            chunks = []
            context_parts = []

            for i, point in enumerate(results, 1):
                payload = point.payload or {}
                content = payload.get("content", "")
                enhanced = payload.get("enhanced_content", "")
                paper_title = payload.get("title", payload.get("document_name", "Unknown"))
                arxiv_id = payload.get("arxiv_id", "")
                doc_name = payload.get("document_name", "")
                section = payload.get("section_title", "")

                # Prefer enhanced content if available
                display_content = enhanced if enhanced else content

                chunks.append(RAGChunk(
                    content=display_content[:500] if len(display_content) > 500 else display_content,
                    paper_title=paper_title,
                    arxiv_id=arxiv_id,
                    section=section,
                    relevance_score=1.0,  # No score for direct fetch
                ))

                source_ref = f"arXiv:{arxiv_id}" if arxiv_id else f"Doc:{doc_name}"
                context_parts.append(f"[{i}] From '{paper_title}' ({source_ref}):\n{display_content[:800]}")

            rag_text = "\n\n".join(context_parts)
            return rag_text, chunks

        except Exception as e:
            print(f"Direct fetch error: {e}")
            return None, []

    def _call_rag_directly(
        self,
        query: str,
        selected_sources: Optional[list[str]] = None,
        tenant_id: Optional[str] = None,
        department: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> tuple[str, list]:
        """Call RAG tool directly without going through the agent.

        Args:
            query: Search query
            selected_sources: Optional list of arxiv_ids or document names to filter
            tenant_id: User's tenant ID for visibility filtering
            department: User's department for visibility filtering
            user_id: User's ID for visibility filtering

        Returns:
            Tuple of (rag_result_text, rag_chunks)
        """
        from ..tools.rag_tool import get_qdrant_client, get_embedding, build_visibility_filter
        from qdrant_client.models import Filter, FieldCondition, MatchAny

        settings = get_settings()

        try:
            client = get_qdrant_client()
            query_embedding = get_embedding(query)

            # Build filter based on what's available
            query_filter = None

            # If sources are selected, filter by them
            if selected_sources and len(selected_sources) > 0:
                source_filter = Filter(
                    should=[  # OR condition
                        FieldCondition(key="arxiv_id", match=MatchAny(any=selected_sources)),
                        FieldCondition(key="document_name", match=MatchAny(any=selected_sources)),
                    ]
                )

                # Combine with visibility filter if available
                if tenant_id and department and user_id:
                    visibility_filter = build_visibility_filter(tenant_id, department, user_id)
                    query_filter = Filter(must=[visibility_filter, source_filter])
                else:
                    query_filter = source_filter
            else:
                # No sources selected - just use visibility filter if available
                if tenant_id and department and user_id:
                    query_filter = build_visibility_filter(tenant_id, department, user_id)
                # If no visibility info either, query_filter stays None (search all)

            # Query Qdrant
            results = client.query_points(
                collection_name=settings.qdrant_collection,
                query=query_embedding,
                query_filter=query_filter,
                limit=5,
                with_payload=True,
            )

            if not results.points:
                return None, []

            # Check relevance - if scores are too low, don't use RAG
            # This helps filter out irrelevant results when searching all docs
            MIN_RELEVANCE_SCORE = 0.3  # Adjust this threshold as needed
            relevant_points = [p for p in results.points if p.score >= MIN_RELEVANCE_SCORE]

            if not relevant_points:
                return None, []

            # Format results
            chunks = []
            context_parts = []

            for i, point in enumerate(relevant_points, 1):
                payload = point.payload or {}
                content = payload.get("content", "")
                paper_title = payload.get("title", "Unknown Paper")
                arxiv_id = payload.get("arxiv_id", "")
                doc_name = payload.get("document_name", "")
                section = payload.get("section_title", "")
                score = point.score

                chunks.append(RAGChunk(
                    content=content[:500] if len(content) > 500 else content,
                    paper_title=paper_title,
                    arxiv_id=arxiv_id,
                    section=section,
                    relevance_score=score,
                ))

                # Use arxiv_id if available, otherwise document name
                source_ref = f"arXiv:{arxiv_id}" if arxiv_id else f"Doc:{doc_name}"
                context_parts.append(f"[{i}] From '{paper_title}' ({source_ref}):\n{content[:800]}")

            rag_text = "\n\n".join(context_parts)
            return rag_text, chunks

        except Exception as e:
            print(f"RAG error: {e}")
            return None, []

    async def process_message(
        self,
        message: str,
        thread_id: str,
        user_id: Optional[str] = None,
        selected_sources: Optional[list[str]] = None,
        tenant_id: Optional[str] = None,
        department: Optional[str] = None,
    ) -> ChatResponse:
        """Process a user message through the agent.

        Uses LangGraph with PostgreSQL checkpointing for conversation memory.

        Args:
            message: User's message
            thread_id: Conversation thread ID (used as LangGraph thread_id)
            user_id: Optional user ID for RBAC
            selected_sources: Optional list of arxiv_ids/document names to filter RAG
            tenant_id: Optional tenant ID for visibility filtering
            department: Optional department for visibility filtering

        Returns:
            ChatResponse with agent's response
        """
        # Store user message in database
        await self._store_message(
            thread_id=thread_id,
            user_id=user_id,
            role="user",
            content=message,
        )

        try:
            # Check if this is a tool-specific query (calculator, expense)
            is_tool_query = self._is_tool_specific_query(message)

            rag_context = None
            augmented_message = message

            # ALWAYS try RAG first, unless it's a tool-specific query
            if not is_tool_query:
                # Check if user explicitly references selected documents
                # e.g., "Generate post using the selected document"
                references_docs = self._references_selected_documents(message)

                if selected_sources and len(selected_sources) > 0 and references_docs:
                    # User wants content FROM the selected docs directly
                    # Fetch top chunks without semantic filtering
                    rag_text, rag_chunks = self._fetch_top_chunks_from_sources(
                        selected_sources,
                        tenant_id=tenant_id,
                        department=department,
                        user_id=user_id,
                        limit=5,
                    )
                else:
                    # Normal semantic search
                    rag_text, rag_chunks = self._call_rag_directly(
                        message,
                        selected_sources=selected_sources if selected_sources else None,
                        tenant_id=tenant_id,
                        department=department,
                        user_id=user_id
                    )

                if rag_text and rag_chunks:
                    # RAG found relevant content - augment the message
                    if selected_sources and len(selected_sources) > 0:
                        # Specific sources selected - be strict
                        augmented_message = f"""Answer the following question based ONLY on the provided context from the selected research papers.
Do not use any external knowledge. If the context doesn't contain enough information to answer the question, say "The selected papers don't contain information about this topic."

CONTEXT FROM SELECTED PAPERS:
{rag_text}

USER QUESTION: {message}

Remember: Answer ONLY based on the context above."""
                    else:
                        # No specific sources - use RAG context but allow some flexibility
                        augmented_message = f"""Answer the following question using the provided context from the knowledge base.
Use this context as your primary source of information. If the context is relevant, base your answer on it.
If the context is not relevant to the question, you may use your general knowledge to answer.

CONTEXT FROM KNOWLEDGE BASE:
{rag_text}

USER QUESTION: {message}

Prioritize information from the context above when relevant."""

                    rag_context = RAGContext(query=message, chunks=rag_chunks)
                elif selected_sources and len(selected_sources) > 0:
                    # Sources were selected but no relevant content found
                    no_info_response = f"No relevant information was found in the selected sources ({', '.join(selected_sources[:3])}{' and more' if len(selected_sources) > 3 else ''}) for your question. Try selecting different papers or rephrase your question."

                    await self._store_message(
                        thread_id=thread_id,
                        user_id=user_id,
                        role="assistant",
                        content=no_info_response,
                    )

                    return ChatResponse(
                        response=no_info_response,
                        thread_id=thread_id,
                        rag_context=RAGContext(query=message, chunks=[]),
                    )
                # If no sources selected and RAG found nothing, continue to agent (fallback to general LLM)

            # Get agent with checkpointer
            agent = self._get_agent()

            # Set session context for tools (user_id, thread_id, tenant, department)
            set_session_context(
                thread_id=thread_id,
                user_id=user_id,
                tenant_id=tenant_id,
                department=department,
            )

            # LangGraph config with thread_id for memory, selected sources, visibility context,
            # and LangSmith metadata/tags for tracing
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "department": department,
                    "selected_sources": selected_sources,
                },
                "metadata": {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "thread_id": thread_id,
                    "department": department,
                    "operation": "chat",
                    "has_rag_context": rag_context is not None,
                },
                "tags": [
                    f"tenant:{tenant_id or 'default'}",
                    f"user:{user_id or 'anonymous'}",
                    f"dept:{department or 'general'}",
                    "rag" if rag_context else "no-rag",
                ]
            }

            # Build agent input state
            # Pass RAG context in state so agent can use it for content generation tools
            agent_input = {
                "messages": [HumanMessage(content=augmented_message)],
            }

            # If we have RAG context (the raw text), pass it in state for tools like twitter_generator
            if rag_context and rag_context.chunks:
                # Build raw context text for tools to use
                raw_context_parts = []
                for chunk in rag_context.chunks:
                    source = f"arXiv:{chunk.arxiv_id}" if chunk.arxiv_id else chunk.paper_title
                    raw_context_parts.append(f"From {source}:\n{chunk.content}")
                agent_input["rag_context"] = "\n\n".join(raw_context_parts)

            # Get current state to know how many messages existed before this invocation
            try:
                current_state = agent.get_state(config)
                messages_before = len(current_state.values.get("messages", [])) if current_state.values else 0
            except Exception as e:
                logger.warning(f"Could not get current state: {e}")
                messages_before = 0

            # Invoke agent with state (wrapped in executor for non-blocking)
            loop = asyncio.get_event_loop()

            def run_agent():
                return agent.invoke(agent_input, config=config)

            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(_executor, run_agent),
                    timeout=settings.agent_timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"Agent execution timed out after {settings.agent_timeout}s")
                raise HTTPException(
                    status_code=408,
                    detail=f"Request timeout - agent took longer than {settings.agent_timeout} seconds"
                )

            # Clear progress tracker
            get_progress_tracker().clear(thread_id)

            # Extract response - only process NEW messages (after messages_before index)
            all_messages = result.get("messages", [])
            # New messages are those added after the existing history
            new_messages = all_messages[messages_before:] if messages_before > 0 else all_messages
            last_message = all_messages[-1] if all_messages else None

            response_content = ""
            tool_calls = None
            tools_used = []
            # Keep forced_rag_context if we did forced RAG, otherwise will be populated from agent
            forced_rag_context = rag_context
            rag_query = None
            requires_approval = False
            approval_type = None
            pending_content = None

            # Process only NEW messages to extract tool usage and RAG results
            tool_call_map = {}  # Map tool call IDs to tool names and args

            for msg in new_messages:
                # Collect tool calls from AIMessages
                if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_name = tc.get("name")
                        tool_id = tc.get("id")
                        tool_args = tc.get("args", {})

                        if tool_id:
                            tool_call_map[tool_id] = {
                                "name": tool_name,
                                "args": tool_args
                            }

                        # Capture RAG query from rag_retriever args
                        if tool_name == "rag_retriever":
                            rag_query = tool_args.get("query", "")

                        tools_used.append(ToolUsage(
                            name=tool_name,
                            args=tool_args,
                            result=None  # Will be filled from ToolMessage
                        ))

                # Extract results from ToolMessages
                if isinstance(msg, ToolMessage):
                    tool_id = getattr(msg, "tool_call_id", None)
                    tool_content = msg.content if hasattr(msg, "content") else ""
                    tool_name = getattr(msg, "name", None) or (
                        tool_call_map.get(tool_id, {}).get("name") if tool_id else None
                    )

                    # Update tool result in tools_used
                    for tu in tools_used:
                        if tu.name == tool_name and tu.result is None:
                            tu.result = tool_content[:500] if len(tool_content) > 500 else tool_content
                            break

                    # Check for content generators that require HITL approval
                    if tool_name == "twitter_generator" and tool_content and "Error" not in tool_content:
                        requires_approval = True
                        approval_type = "tweet"
                        pending_content = tool_content
                    elif tool_name == "linkedin_generator" and tool_content and "Error" not in tool_content:
                        requires_approval = True
                        approval_type = "linkedin"
                        pending_content = tool_content

                    # Extract RAG chunks if this was a rag_retriever call (only if we didn't force RAG)
                    if tool_name == "rag_retriever" and "Retrieved Context" in tool_content and not forced_rag_context:
                        rag_chunks = self._parse_rag_chunks(tool_content)
                        # Get the query from tool_call_map if not already captured
                        if not rag_query and tool_id and tool_id in tool_call_map:
                            rag_query = tool_call_map[tool_id].get("args", {}).get("query", "")
                        forced_rag_context = RAGContext(query=rag_query or "", chunks=rag_chunks)

            if last_message:
                if isinstance(last_message, AIMessage):
                    response_content = last_message.content

                    # Check for tool calls
                    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                        tool_calls = [
                            {
                                "name": tc.get("name"),
                                "args": tc.get("args"),
                            }
                            for tc in last_message.tool_calls
                        ]
                else:
                    response_content = str(last_message.content)

            # Store assistant response
            await self._store_message(
                thread_id=thread_id,
                user_id=user_id,
                role="assistant",
                content=response_content,
                tool_calls=tool_calls,
            )

            return ChatResponse(
                response=response_content,
                thread_id=thread_id,
                tool_calls=tool_calls,
                tools_used=tools_used if tools_used else None,
                rag_context=forced_rag_context,
                requires_approval=requires_approval,
                approval_type=approval_type,
                pending_content=pending_content,
            )

        except Exception as e:
            # Fallback for when agent fails
            error_response = f"I encountered an issue: {str(e)}. Please try again."

            await self._store_message(
                thread_id=thread_id,
                user_id=user_id,
                role="assistant",
                content=error_response,
            )

            return ChatResponse(
                response=error_response,
                thread_id=thread_id,
                tool_calls=None,
                requires_approval=False,
            )

    async def handle_approval(
        self,
        thread_id: str,
        approval_type: str,
        approved: bool,
    ) -> dict:
        """Handle HITL approval for content.

        Uses LangGraph's Command to resume execution.

        Args:
            thread_id: Conversation thread ID
            approval_type: Type of content ("tweet" or "linkedin")
            approved: Whether content is approved

        Returns:
            Result of approval handling
        """
        from langgraph.types import Command

        try:
            agent = self._get_agent()

            config = {"configurable": {"thread_id": thread_id}}

            # Resume with approval decision
            result = agent.invoke(
                Command(resume={"approved": approved}),
                config=config,
            )

            if approved:
                # Store the approved content
                if approval_type == "tweet":
                    await self._store_approved_tweet(thread_id, result)
                elif approval_type == "linkedin":
                    await self._store_approved_post(thread_id, result)

            return {
                "status": "approved" if approved else "rejected",
                "type": approval_type,
                "thread_id": thread_id,
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "thread_id": thread_id,
            }

    async def get_conversation_history(self, thread_id: str) -> list[dict]:
        """Get conversation history from database.

        Args:
            thread_id: Conversation thread ID

        Returns:
            List of messages
        """
        result = await self.db.execute(
            select(Message)
            .where(Message.thread_id == thread_id)
            .order_by(Message.created_at.asc())
        )
        messages = result.scalars().all()

        return [
            {
                "id": str(msg.id),
                "role": msg.role,
                "content": msg.content,
                "tool_calls": msg.tool_calls,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
        ]

    def _parse_rag_chunks(self, rag_output: str) -> list[RAGChunk]:
        """Parse RAG retriever output into structured chunks."""
        chunks = []
        import re

        # Split by chunk separators
        parts = rag_output.split("---")

        for part in parts:
            part = part.strip()
            if not part or "Retrieved Context" in part or "Use this context" in part:
                continue

            chunk = RAGChunk(content="")

            # Extract paper title
            title_match = re.search(r'\*\*\[\d+\]\s*(.+?)\*\*', part)
            if title_match:
                chunk.paper_title = title_match.group(1).strip()

            # Extract arXiv ID
            arxiv_match = re.search(r'arXiv:\s*(\S+)', part)
            if arxiv_match:
                chunk.arxiv_id = arxiv_match.group(1).strip()

            # Extract section
            section_match = re.search(r'Section:\s*(.+)', part)
            if section_match:
                chunk.section = section_match.group(1).strip()

            # Extract relevance score
            score_match = re.search(r'Relevance:\s*([\d.]+)', part)
            if score_match:
                try:
                    chunk.relevance_score = float(score_match.group(1))
                except ValueError:
                    pass

            # Extract content (everything after the metadata)
            lines = part.split('\n')
            content_lines = []
            found_metadata = False
            for line in lines:
                if 'Relevance:' in line:
                    found_metadata = True
                    continue
                if found_metadata and line.strip():
                    content_lines.append(line.strip())

            chunk.content = ' '.join(content_lines)[:300] if content_lines else part[:300]

            if chunk.content or chunk.paper_title:
                chunks.append(chunk)

        return chunks

    async def _store_message(
        self,
        thread_id: str,
        user_id: Optional[str],
        role: str,
        content: str,
        tool_calls: Optional[list] = None,
        tool_name: Optional[str] = None,
    ):
        """Store a message in the database."""
        from uuid import UUID

        user_uuid = None
        if user_id:
            try:
                user_uuid = UUID(user_id)
            except ValueError:
                pass

        message = Message(
            thread_id=thread_id,
            user_id=user_uuid,
            role=role,
            content=content,
            tool_calls={"calls": tool_calls} if tool_calls else None,
            tool_name=tool_name,
        )
        self.db.add(message)
        await self.db.flush()

    async def _store_approved_tweet(self, thread_id: str, result: dict):
        """Store an approved tweet."""
        # Extract tweet content from result
        messages = result.get("messages", [])
        tweet_content = None

        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content:
                if len(msg.content) <= 280:
                    tweet_content = msg.content
                    break

        if tweet_content:
            tweet = Tweet(
                thread_id=thread_id,
                topic="Generated tweet",
                final_content=tweet_content,
                approved=True,
            )
            self.db.add(tweet)
            await self.db.flush()

    async def _store_approved_post(self, thread_id: str, result: dict):
        """Store an approved LinkedIn post."""
        messages = result.get("messages", [])
        post_content = None

        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content:
                post_content = msg.content
                break

        if post_content:
            post = LinkedInPost(
                thread_id=thread_id,
                topic="Generated post",
                final_content=post_content,
            )
            self.db.add(post)
            await self.db.flush()

    async def process_message_streaming(
        self,
        message: str,
        thread_id: str,
        user_id: Optional[str] = None,
        selected_sources: Optional[list[str]] = None,
        tenant_id: Optional[str] = None,
        department: Optional[str] = None,
    ):
        """Process a message with streaming status updates.

        Yields status events as the processing progresses:
        - {"type": "status", "status": "searching", "message": "Searching knowledge base..."}
        - {"type": "status", "status": "analyzing", "message": "Analyzing documents..."}
        - {"type": "status", "status": "generating", "message": "Generating response..."}
        - {"type": "result", "data": <ChatResponse dict>}

        Args:
            message: User's message
            thread_id: Conversation thread ID
            user_id: Optional user ID
            selected_sources: Optional list of source IDs to filter
            tenant_id: Optional tenant ID for visibility filtering
            department: Optional department for visibility filtering
        """
        import asyncio

        # Store user message
        await self._store_message(
            thread_id=thread_id,
            user_id=user_id,
            role="user",
            content=message,
        )

        try:
            # Check if this is a tool-specific query
            is_tool_query = self._is_tool_specific_query(message)

            rag_context = None
            augmented_message = message

            if not is_tool_query:
                # Yield status: searching
                yield {"type": "status", "status": "searching", "message": "Searching knowledge base..."}
                await asyncio.sleep(0.1)  # Small delay to ensure event is sent

                # Check if user references selected documents
                references_docs = self._references_selected_documents(message)

                if selected_sources and len(selected_sources) > 0 and references_docs:
                    yield {"type": "status", "status": "fetching", "message": f"Fetching content from {len(selected_sources)} selected document(s)..."}
                    rag_text, rag_chunks = self._fetch_top_chunks_from_sources(
                        selected_sources,
                        tenant_id=tenant_id,
                        department=department,
                        user_id=user_id,
                        limit=5,
                    )
                else:
                    rag_text, rag_chunks = self._call_rag_directly(
                        message,
                        selected_sources=selected_sources if selected_sources else None,
                        tenant_id=tenant_id,
                        department=department,
                        user_id=user_id
                    )

                if rag_text and rag_chunks:
                    yield {"type": "status", "status": "analyzing", "message": f"Found {len(rag_chunks)} relevant chunks. Analyzing..."}
                    await asyncio.sleep(0.1)

                    if selected_sources and len(selected_sources) > 0:
                        augmented_message = f"""Answer the following question based ONLY on the provided context from the selected research papers.
Do not use any external knowledge. If the context doesn't contain enough information to answer the question, say "The selected papers don't contain information about this topic."

CONTEXT FROM SELECTED PAPERS:
{rag_text}

USER QUESTION: {message}

Remember: Answer ONLY based on the context above."""
                    else:
                        augmented_message = f"""Answer the following question using the provided context from the knowledge base.
Use this context as your primary source of information. If the context is relevant, base your answer on it.
If the context is not relevant to the question, you may use your general knowledge to answer.

CONTEXT FROM KNOWLEDGE BASE:
{rag_text}

USER QUESTION: {message}

Prioritize information from the context above when relevant."""

                    rag_context = RAGContext(query=message, chunks=rag_chunks)
                elif selected_sources and len(selected_sources) > 0:
                    # No results from selected sources
                    no_info_response = f"No relevant information was found in the selected sources ({', '.join(selected_sources[:3])}{' and more' if len(selected_sources) > 3 else ''}) for your question."

                    await self._store_message(
                        thread_id=thread_id,
                        user_id=user_id,
                        role="assistant",
                        content=no_info_response,
                    )

                    yield {
                        "type": "result",
                        "data": {
                            "response": no_info_response,
                            "thread_id": thread_id,
                            "rag_context": {"query": message, "chunks": []},
                        }
                    }
                    return
                else:
                    yield {"type": "status", "status": "searching", "message": "No matching documents found. Using general knowledge..."}
                    await asyncio.sleep(0.1)

            # Yield status: generating
            yield {"type": "status", "status": "generating", "message": "Generating response..."}
            await asyncio.sleep(0.1)

            # Get agent
            agent = self._get_agent()
            progress_tracker = get_progress_tracker()

            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "department": department,
                    "selected_sources": selected_sources,
                },
                "metadata": {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "thread_id": thread_id,
                    "department": department,
                    "operation": "chat_stream",
                    "has_rag_context": rag_context is not None,
                },
                "tags": [
                    f"tenant:{tenant_id or 'default'}",
                    f"user:{user_id or 'anonymous'}",
                    f"dept:{department or 'general'}",
                    "rag" if rag_context else "no-rag",
                    "streaming",
                ]
            }

            agent_input = {"messages": [HumanMessage(content=augmented_message)]}

            if rag_context and rag_context.chunks:
                raw_context_parts = []
                for chunk in rag_context.chunks:
                    source = f"arXiv:{chunk.arxiv_id}" if chunk.arxiv_id else chunk.paper_title
                    raw_context_parts.append(f"From {source}:\n{chunk.content}")
                agent_input["rag_context"] = "\n\n".join(raw_context_parts)

            # Get current state to know how many messages existed before this invocation
            try:
                current_state = agent.get_state(config)
                messages_before = len(current_state.values.get("messages", [])) if current_state.values else 0
            except Exception as e:
                logger.warning(f"Could not get current state for streaming: {e}")
                messages_before = 0

            # Run agent in background thread with session context
            def run_agent_with_context():
                set_session_context(
                    thread_id=thread_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    department=department,
                )
                return agent.invoke(agent_input, config=config)

            loop = asyncio.get_event_loop()
            agent_future = loop.run_in_executor(_executor, run_agent_with_context)

            # Poll for progress while agent runs
            last_progress_msg = None
            last_embedding_update = None
            while not agent_future.done():
                # Check for content generation progress (tweet/linkedin)
                progress = progress_tracker.get(thread_id)
                if progress and progress.message != last_progress_msg:
                    last_progress_msg = progress.message
                    yield {
                        "type": "status",
                        "status": "tool_progress",
                        "message": progress.message,
                        "tool": progress.tool_name,
                        "iteration": progress.iteration,
                        "step": progress.current_step,
                        "quality_score": progress.quality_score,
                    }

                # Check for embedding progress
                embedding_progress = progress_tracker.get_embedding_progress(thread_id)
                if embedding_progress:
                    progress_dict = embedding_progress.to_dict()
                    # Only emit if there's an update (check timestamp or message change)
                    update_key = f"{embedding_progress.current_step}:{embedding_progress.message}:{len(embedding_progress.logs)}"
                    if update_key != last_embedding_update:
                        last_embedding_update = update_key
                        yield {
                            "type": "embedding_progress",
                            "data": progress_dict,
                        }

                await asyncio.sleep(0.3)

            # Get result
            result = await agent_future

            # Clear progress trackers
            progress_tracker.clear(thread_id)
            progress_tracker.clear_embedding(thread_id)

            # Process result - only NEW messages (after messages_before index)
            all_messages = result.get("messages", [])
            new_messages = all_messages[messages_before:] if messages_before > 0 else all_messages
            last_message = all_messages[-1] if all_messages else None

            response_content = ""
            tool_calls = None
            tools_used = []
            forced_rag_context = rag_context
            rag_query = None
            requires_approval = False
            approval_type = None
            pending_content = None

            tool_call_map = {}

            for msg in new_messages:
                if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_name = tc.get("name")
                        tool_id = tc.get("id")
                        tool_args = tc.get("args", {})

                        if tool_id:
                            tool_call_map[tool_id] = {"name": tool_name, "args": tool_args}

                        if tool_name == "rag_retriever":
                            rag_query = tool_args.get("query", "")

                        # Yield status for tool usage
                        tool_display = {
                            "twitter_generator": "Generating tweet...",
                            "linkedin_generator": "Generating LinkedIn post...",
                            "calculator": "Calculating...",
                            "expense_manager": "Managing expenses...",
                            "rag_retriever": "Searching documents...",
                        }.get(tool_name, f"Using {tool_name}...")

                        yield {"type": "status", "status": "tool", "message": tool_display, "tool": tool_name}

                        tools_used.append(ToolUsage(
                            name=tool_name,
                            args=tool_args,
                            result=None
                        ))

                if isinstance(msg, ToolMessage):
                    tool_id = getattr(msg, "tool_call_id", None)
                    tool_content = msg.content if hasattr(msg, "content") else ""
                    tool_name = getattr(msg, "name", None) or (
                        tool_call_map.get(tool_id, {}).get("name") if tool_id else None
                    )

                    for tu in tools_used:
                        if tu.name == tool_name and tu.result is None:
                            tu.result = tool_content[:500] if len(tool_content) > 500 else tool_content
                            break

                    # Check for content generators that require HITL approval
                    if tool_name == "twitter_generator" and tool_content and "Error" not in tool_content:
                        requires_approval = True
                        approval_type = "tweet"
                        pending_content = tool_content
                    elif tool_name == "linkedin_generator" and tool_content and "Error" not in tool_content:
                        requires_approval = True
                        approval_type = "linkedin"
                        pending_content = tool_content

                    if tool_name == "rag_retriever" and "Retrieved Context" in tool_content and not forced_rag_context:
                        rag_chunks = self._parse_rag_chunks(tool_content)
                        if not rag_query and tool_id and tool_id in tool_call_map:
                            rag_query = tool_call_map[tool_id].get("args", {}).get("query", "")
                        forced_rag_context = RAGContext(query=rag_query or "", chunks=rag_chunks)

            if last_message:
                if isinstance(last_message, AIMessage):
                    response_content = last_message.content

                    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                        tool_calls = [
                            {"name": tc.get("name"), "args": tc.get("args")}
                            for tc in last_message.tool_calls
                        ]
                else:
                    response_content = str(last_message.content)

            # Store assistant response
            await self._store_message(
                thread_id=thread_id,
                user_id=user_id,
                role="assistant",
                content=response_content,
                tool_calls=tool_calls,
            )

            # Stream the response text in chunks for real-time display
            if response_content:
                yield {"type": "stream_start"}

                # Split response into words and stream them in small chunks
                words = response_content.split(' ')
                chunk_size = 3  # Send 3 words at a time for smooth streaming
                for i in range(0, len(words), chunk_size):
                    chunk = ' '.join(words[i:i + chunk_size])
                    # Add space unless it's the last chunk
                    if i + chunk_size < len(words):
                        chunk += ' '
                    yield {"type": "text_chunk", "content": chunk}
                    await asyncio.sleep(0.02)  # Small delay for visual effect

                # Send stream end with metadata
                yield {
                    "type": "stream_end",
                    "tool_calls": tool_calls,
                    "tools_used": [{"name": t.name, "args": t.args, "result": t.result} for t in tools_used] if tools_used else None,
                    "rag_context": {
                        "query": forced_rag_context.query if forced_rag_context else None,
                        "chunks": [
                            {
                                "content": c.content,
                                "paper_title": c.paper_title,
                                "arxiv_id": c.arxiv_id,
                                "section": c.section,
                                "relevance_score": c.relevance_score,
                            }
                            for c in forced_rag_context.chunks
                        ] if forced_rag_context else [],
                    } if forced_rag_context else None,
                    "requires_approval": requires_approval,
                    "approval_type": approval_type,
                    "pending_content": pending_content,
                }
            else:
                # Fallback for empty response
                yield {
                    "type": "result",
                    "data": {
                        "response": response_content,
                        "thread_id": thread_id,
                        "tool_calls": tool_calls,
                        "tools_used": [{"name": t.name, "args": t.args, "result": t.result} for t in tools_used] if tools_used else None,
                        "rag_context": {
                            "query": forced_rag_context.query if forced_rag_context else None,
                            "chunks": [
                                {
                                    "content": c.content,
                                    "paper_title": c.paper_title,
                                    "arxiv_id": c.arxiv_id,
                                    "section": c.section,
                                    "relevance_score": c.relevance_score,
                                }
                                for c in forced_rag_context.chunks
                            ] if forced_rag_context else [],
                        } if forced_rag_context else None,
                        "requires_approval": requires_approval,
                        "approval_type": approval_type,
                        "pending_content": pending_content,
                    }
                }

        except Exception as e:
            error_response = f"I encountered an issue: {str(e)}. Please try again."

            await self._store_message(
                thread_id=thread_id,
                user_id=user_id,
                role="assistant",
                content=error_response,
            )

            yield {
                "type": "result",
                "data": {
                    "response": error_response,
                    "thread_id": thread_id,
                    "tool_calls": None,
                    "requires_approval": False,
                }
            }
