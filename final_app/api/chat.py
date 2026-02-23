"""Chat API endpoint for agent interactions."""

import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Optional, AsyncGenerator
from uuid import uuid4, UUID

from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, Form, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.schemas import ChatRequest, ChatResponse
from ..models.orm import Message, User
from ..services.agent_service import AgentService
from ..services.document_context_service import DocumentContextService
from ..services.rate_limiter import (
    get_rate_limiter,
    get_global_rate_limiter,
    RateLimitResult,
    QueuedRequest,
)
from ..services.request_logger import log_request, RequestTimer
from ..services.cache_service import get_cache_service
from ..config import get_settings
from .dependencies import get_user_tier, record_token_usage

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)

# File size limit in bytes
MAX_FILE_SIZE = settings.max_file_size_mb * 1024 * 1024


async def check_user_rate_limits(user_id: Optional[str], db: AsyncSession) -> tuple[str, str, RateLimitResult]:
    """Check per-user rate limits and return user info with result.

    Returns:
        Tuple of (actual_user_id, tier, rate_limit_result)

    Raises:
        HTTPException 429 if user rate limit exceeded
    """
    rate_limiter = get_rate_limiter()
    actual_user_id, tier = await get_user_tier(user_id, db)

    # Check per-user request rate limit
    result = rate_limiter.check_request_limit(actual_user_id, tier)

    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "User rate limit exceeded",
                "message": result.reason,
                "limit": result.limit,
                "reset_in_seconds": result.reset_in_seconds,
            },
            headers={
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(result.reset_in_seconds),
                "Retry-After": str(result.reset_in_seconds),
            },
        )

    # Check token limit
    token_result = rate_limiter.check_token_limit(actual_user_id, tier)
    if not token_result.allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Token limit exceeded",
                "message": token_result.reason,
                "limit": token_result.limit,
                "reset_in_seconds": token_result.reset_in_seconds,
            },
        )

    return actual_user_id, tier, result


# Keep old name for backwards compatibility
async def check_rate_limits(user_id: Optional[str], db: AsyncSession) -> tuple[str, str, RateLimitResult]:
    """Alias for check_user_rate_limits for backwards compatibility."""
    return await check_user_rate_limits(user_id, db)


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a message to the agent and get a response."""
    # Check rate limits
    actual_user_id, tier, rate_result = await check_rate_limits(request.user_id, db)

    # Generate thread_id if not provided
    thread_id = request.thread_id or str(uuid4())

    try:
        agent_service = AgentService(db)
        response = await agent_service.process_message(
            message=request.message,
            thread_id=thread_id,
            user_id=request.user_id,
            selected_sources=request.selected_sources,
            tenant_id=request.tenant_id,
            department=request.department,
        )

        # Record token usage (estimate based on response length)
        # In production, you'd get actual token counts from the LLM response
        estimated_tokens = len(request.message.split()) * 2 + len(str(response.response).split()) * 2
        record_token_usage(actual_user_id, estimated_tokens, tier)

        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    fastapi_request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """Send a message to the agent with streaming status updates.

    Implements two-level rate limiting:
    1. Per-user rate limit (25 req/min for free/power, unlimited for super)
    2. Global system rate limit (500 req/min for entire system)

    If global limit is exceeded, requests are queued and processed with backoff.
    SSE updates are streamed to show queue position and processing status.

    Returns Server-Sent Events with:
    - queue: Queue position updates (if queued)
    - status: Current processing stage
    - result: Final response (when complete)
    """
    request_start_time = time.time()

    # 1. Check per-user rate limits
    try:
        actual_user_id, tier, user_rate_result = await check_user_rate_limits(request.user_id, db)
    except HTTPException as e:
        # Capture exception details BEFORE defining generator (avoids closure bug)
        error_detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        error_message = error_detail.get('message', 'Rate limit exceeded') if isinstance(error_detail, dict) else str(error_detail)
        reset_in = error_detail.get('reset_in_seconds', 60) if isinstance(error_detail, dict) else 60

        # Log rate-limited request
        await log_request(
            db=db,
            endpoint="chat_stream",
            message=request.message,
            user_id=request.user_id,
            thread_id=request.thread_id,
            tenant_id=request.tenant_id,
            department=request.department,
            tier="unknown",
            status="rate_limited",
            rate_limited=True,
            error_message=str(error_detail),
        )

        async def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': error_message, 'rate_limit': True, 'reset_in': reset_in})}\n\n"
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    thread_id = request.thread_id or str(uuid4())
    request_id = str(uuid4())

    # 2. Check global rate limit
    global_limiter = get_global_rate_limiter()
    global_result = global_limiter.check_global_limit(increment=True)

    async def process_request(was_queued: bool = False) -> AsyncGenerator[str, None]:
        """Process the actual chat request with caching."""
        process_start = time.time()
        total_tokens = 0
        status = "success"
        error_msg = None
        from_cache = False

        try:
            # 1. Check cache first
            cache_service = get_cache_service()
            cache_result = cache_service.lookup(
                question=request.message,
                tenant_id=request.tenant_id or "default",
                department=request.department,
            )

            if cache_result.hit:
                # Cache hit - return cached answer
                from_cache = True
                similarity = cache_result.similarity or 1.0
                is_exact = similarity == 1.0
                cache_type = "exact" if is_exact else "semantic"
                yield f"data: {json.dumps({'type': 'status', 'message': f'Retrieved from cache ({cache_type} match)', 'status': 'cache_hit'})}\n\n"

                # Build result event with cached data
                cached_entry = cache_result.entry
                result_data = {
                    "response": cache_result.answer,
                    "tools_used": [{"name": t} for t in (cached_entry.tools_used or [])] if cached_entry.tools_used else None,
                    "from_cache": True,
                    "cache_info": {
                        "cached_at": cached_entry.created_at,
                        "used_rag": cached_entry.used_rag,
                        "similarity": similarity,
                        "match_type": cache_type,
                    }
                }
                yield f"data: {json.dumps({'type': 'result', 'data': result_data})}\n\n"

                # Estimate tokens for cached response (minimal since no LLM call)
                total_tokens = len(request.message.split()) + len(cache_result.answer.split())

            else:
                # Cache miss - process normally
                agent_service = AgentService(db)
                response_text = ""
                tools_used = []
                used_rag = False

                streaming_content = ""  # Accumulate streamed content
                async for event in agent_service.process_message_streaming(
                    message=request.message,
                    thread_id=thread_id,
                    user_id=request.user_id,
                    selected_sources=request.selected_sources,
                    tenant_id=request.tenant_id,
                    department=request.department,
                ):
                    event_type = event.get("type")

                    # Accumulate streamed text chunks
                    if event_type == "text_chunk":
                        streaming_content += event.get("content", "")

                    # Handle stream_end (streaming responses)
                    elif event_type == "stream_end":
                        response_text = streaming_content
                        total_tokens = len(request.message.split()) * 2 + len(response_text.split()) * 2

                        # Track tools used
                        if event.get("tools_used"):
                            tools_used = [t.get("name") for t in event["tools_used"] if t.get("name")]
                            used_rag = any("rag" in t.lower() for t in tools_used)

                        # Add from_cache flag
                        event["from_cache"] = False

                    # Handle result events (non-streaming responses)
                    elif event_type == "result":
                        data = event.get("data", {})
                        response_text = data.get("response", "")
                        total_tokens = len(request.message.split()) * 2 + len(response_text.split()) * 2

                        # Track tools used
                        if data.get("tools_used"):
                            tools_used = [t.get("name") for t in data["tools_used"] if t.get("name")]
                            # Check if RAG was used
                            used_rag = any("rag" in t.lower() for t in tools_used)

                        # Add from_cache flag to result
                        data["from_cache"] = False
                        event["data"] = data

                    yield f"data: {json.dumps(event)}\n\n"

                # Store in cache after successful response
                if response_text and status == "success":
                    cache_service.store(
                        question=request.message,
                        answer=response_text,
                        tenant_id=request.tenant_id or "default",
                        department=request.department,
                        used_rag=used_rag,
                        tools_used=tools_used if tools_used else None,
                    )

            if total_tokens > 0:
                record_token_usage(actual_user_id, total_tokens, tier)

        except Exception as e:
            status = "error"
            error_msg = str(e)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # Log the request
            response_time_ms = int((time.time() - request_start_time) * 1000)
            await log_request(
                db=db,
                endpoint="chat_stream",
                message=request.message,
                user_id=actual_user_id,
                thread_id=thread_id,
                tenant_id=request.tenant_id,
                department=request.department,
                tier=tier,
                status="cache_hit" if from_cache else status,
                response_time_ms=response_time_ms,
                tokens_used=total_tokens if total_tokens > 0 else None,
                queued=was_queued,
                error_message=error_msg,
            )

    async def queued_event_generator() -> AsyncGenerator[str, None]:
        """Handle queued request with status updates."""
        # Decrement global count since we're queuing, not processing immediately
        global_limiter.decrement_global_count()

        # Create queued request
        queued_req = QueuedRequest(
            request_id=request_id,
            user_id=actual_user_id,
            tier=tier,
            message=request.message,
            thread_id=thread_id,
            selected_sources=request.selected_sources,
            tenant_id=request.tenant_id,
            department=request.department,
            created_at=time.time(),
            attempt=1,
        )

        # Add to queue
        position = global_limiter.add_to_queue(queued_req)

        if position == -1:
            # Queue is full
            yield f"data: {json.dumps({'type': 'error', 'message': 'System is busy. Please try again later.', 'queue_full': True})}\n\n"
            return

        # Send initial queue position
        yield f"data: {json.dumps({'type': 'queue', 'status': 'queued', 'position': position, 'message': f'You are #{position} in queue'})}\n\n"

        start_time = time.time()
        max_wait = settings.global_queue_max_wait_seconds
        last_position = position

        # Wait for our turn with periodic updates
        while True:
            elapsed = time.time() - start_time

            # Check timeout
            if elapsed > max_wait:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Request timed out in queue. Please try again.', 'timeout': True})}\n\n"
                return

            # Check current position
            current_position = global_limiter.get_queue_position(request_id)

            if current_position == -1:
                # Not in queue anymore (processed by worker or error)
                yield f"data: {json.dumps({'type': 'error', 'message': 'Request lost from queue. Please try again.'})}\n\n"
                return

            if current_position == 0:
                # Currently being processed
                yield f"data: {json.dumps({'type': 'queue', 'status': 'processing', 'message': 'Processing your request...'})}\n\n"
                break

            # Update position if changed
            if current_position != last_position:
                yield f"data: {json.dumps({'type': 'queue', 'status': 'waiting', 'position': current_position, 'message': f'You are #{current_position} in queue'})}\n\n"
                last_position = current_position

            # Check if global limit has capacity now
            check_result = global_limiter.check_global_limit(increment=False)
            if check_result.allowed and check_result.current_count < check_result.limit:
                # We have capacity - try to process
                # Remove from queue first
                next_req = global_limiter.get_next_from_queue()
                if next_req and next_req.request_id == request_id:
                    # It's our turn - increment global counter and process
                    global_limiter.check_global_limit(increment=True)
                    global_limiter.mark_processing(request_id)
                    yield f"data: {json.dumps({'type': 'queue', 'status': 'processing', 'message': 'Processing your request...'})}\n\n"
                    break
                elif next_req:
                    # Put it back, it's not ours
                    global_limiter.requeue_request(next_req)

            # Wait before checking again
            await asyncio.sleep(0.5)

        # Now process the actual request
        try:
            async for event in process_request(was_queued=True):
                yield event
        finally:
            global_limiter.mark_complete(request_id)

    # Decide whether to process immediately or queue
    if global_result.allowed:
        # Process immediately
        return StreamingResponse(
            process_request(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-RateLimit-Limit": str(user_rate_result.limit),
                "X-RateLimit-Remaining": str(user_rate_result.remaining),
                "X-Global-RateLimit-Limit": str(global_result.limit),
                "X-Global-RateLimit-Remaining": str(global_result.limit - global_result.current_count),
            },
        )
    else:
        # Queue the request
        return StreamingResponse(
            queued_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-RateLimit-Limit": str(user_rate_result.limit),
                "X-RateLimit-Remaining": str(user_rate_result.remaining),
                "X-Global-RateLimit-Limit": str(global_result.limit),
                "X-Global-RateLimit-Remaining": "0",
                "X-Queue-Position": "pending",
            },
        )


@router.post("/stream-with-file")
async def chat_stream_with_file(
    message: str = Form(...),
    thread_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    tenant_id: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    add_to_knowledge_base: bool = Form(False),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Chat with an attached document.

    For documents ≤5 pages: Extracts full text and passes to LLM.
    For documents >5 pages: Embeds document and performs RAG query.

    If add_to_knowledge_base is True, the document is permanently embedded.
    """
    # Check rate limits before starting
    try:
        actual_user_id, tier, rate_result = await check_rate_limits(user_id, db)
    except HTTPException as e:
        # Capture exception details BEFORE defining generator (avoids closure bug)
        error_detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        error_message = error_detail.get('message', 'Rate limit exceeded') if isinstance(error_detail, dict) else str(error_detail)
        reset_in = error_detail.get('reset_in_seconds', 60) if isinstance(error_detail, dict) else 60

        async def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': error_message, 'rate_limit': True, 'reset_in': reset_in})}\n\n"
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    thread_id = thread_id or str(uuid4())

    # Validate file type
    if not file.filename.lower().endswith('.pdf'):
        async def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Only PDF files are supported'})}\n\n"
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    # Save uploaded file to temp location with size check
    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, file.filename)

    try:
        content = await file.read()

        # Check file size
        if len(content) > MAX_FILE_SIZE:
            max_mb = settings.max_file_size_mb
            actual_mb = len(content) / (1024 * 1024)
            async def error_gen():
                yield f"data: {json.dumps({'type': 'error', 'message': f'File too large ({actual_mb:.1f}MB). Maximum size: {max_mb}MB'})}\n\n"
            return StreamingResponse(error_gen(), media_type="text/event-stream")

        with open(temp_path, 'wb') as f:
            f.write(content)
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        async def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': f'Failed to save file: {str(e)}'})}\n\n"
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    async def event_generator() -> AsyncGenerator[str, None]:
        total_tokens = 0
        try:
            # Process document and get context
            doc_service = DocumentContextService()
            agent_service = AgentService(db)

            yield f"data: {json.dumps({'type': 'status', 'message': 'Processing document...', 'status': 'processing_document'})}\n\n"

            # Process the document with keep-alive messages during long embedding
            loop = asyncio.get_event_loop()

            # Start document processing in background
            doc_future = loop.run_in_executor(
                None,
                lambda: doc_service.process_for_chat(
                    file_path=temp_path,
                    filename=file.filename,
                    user_id=user_id or "anonymous",
                    tenant_id=tenant_id or "default",
                    department=department or "general",
                    add_to_knowledge_base=add_to_knowledge_base,
                    query=message,  # For RAG query if needed
                )
            )

            # Send keep-alive messages while waiting for embedding to complete
            elapsed = 0
            while not doc_future.done():
                await asyncio.sleep(2)  # Check every 2 seconds
                elapsed += 2
                if add_to_knowledge_base:
                    # Send progress for long embedding operations
                    yield f"data: {json.dumps({'type': 'status', 'message': f'Embedding document... ({elapsed}s)', 'status': 'embedding'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'status', 'message': f'Processing... ({elapsed}s)', 'status': 'processing'})}\n\n"

            # Get the result
            doc_result = await doc_future

            if doc_result.get("error"):
                yield f"data: {json.dumps({'type': 'error', 'message': doc_result['error']})}\n\n"
                return

            # Build context message
            processing_method = doc_result.get("method", "unknown")
            page_count = doc_result.get("page_count", 0)

            if processing_method == "full_text":
                yield f"data: {json.dumps({'type': 'status', 'message': f'Document loaded ({page_count} pages) - using full context', 'status': 'document_ready'})}\n\n"
            else:
                chunks_used = doc_result.get("chunks_retrieved", 0)
                yield f"data: {json.dumps({'type': 'status', 'message': f'Document embedded ({page_count} pages) - retrieved {chunks_used} relevant chunks', 'status': 'document_ready'})}\n\n"

            # Add document context to the message
            document_context = doc_result.get("context", "")
            enhanced_message = f"""The user has attached a document: "{file.filename}"

Here is the relevant content from the document:

<document_context>
{document_context}
</document_context>

User's question: {message}

Please answer based on the document content provided above."""

            # Stream the agent response
            attached_doc_info = {
                "filename": file.filename,
                "page_count": page_count,
                "method": processing_method,
                "added_to_kb": add_to_knowledge_base and doc_result.get("embedded", False),
            }

            async for event in agent_service.process_message_streaming(
                message=enhanced_message,
                thread_id=thread_id,
                user_id=user_id,
                selected_sources=None,  # Don't use other sources, focus on attached doc
                tenant_id=tenant_id,
                department=department,
            ):
                # Add document info to result/stream_end events and track tokens
                if event.get("type") == "result":
                    event["data"]["attached_document"] = attached_doc_info
                    # Estimate tokens
                    response_text = event.get("data", {}).get("response", "")
                    total_tokens = len(enhanced_message.split()) * 2 + len(response_text.split()) * 2
                elif event.get("type") == "stream_end":
                    event["attached_document"] = attached_doc_info
                yield f"data: {json.dumps(event)}\n\n"

            # Record token usage
            if total_tokens > 0:
                record_token_usage(actual_user_id, total_tokens, tier)

        except Exception as e:
            logger.error(f"Chat with file error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # Cleanup temp file
            try:
                os.unlink(temp_path)
                os.rmdir(temp_dir)
            except OSError as e:
                logger.warning(f"Failed to cleanup temp file: {e}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-RateLimit-Limit": str(rate_result.limit),
            "X-RateLimit-Remaining": str(rate_result.remaining),
        },
    )


@router.post("/{thread_id}/approve")
async def approve_content(
    thread_id: str,
    approval_type: str,  # "tweet" or "linkedin"
    approved: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject pending content (HITL)."""
    try:
        agent_service = AgentService(db)
        response = await agent_service.handle_approval(
            thread_id=thread_id,
            approval_type=approval_type,
            approved=approved,
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations")
async def list_conversations(
    user_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List all conversations for a user.

    Returns conversations grouped by thread_id with:
    - thread_id
    - title (from first user message)
    - preview (from last message)
    - message_count
    - created_at (first message)
    - updated_at (last message)
    """
    from uuid import UUID

    # Build query to get all messages, optionally filtered by user_id
    query = select(Message).order_by(Message.created_at.asc())

    if user_id:
        try:
            user_uuid = UUID(user_id)
            query = query.where(Message.user_id == user_uuid)
        except ValueError:
            pass

    result = await db.execute(query)
    all_messages = result.scalars().all()

    # Group by thread_id
    threads = {}
    for msg in all_messages:
        tid = msg.thread_id
        if tid not in threads:
            threads[tid] = {
                "id": tid,
                "messages": [],
                "created_at": msg.created_at,
                "updated_at": msg.created_at,
            }
        threads[tid]["messages"].append(msg)
        threads[tid]["updated_at"] = msg.created_at

    # Build conversation summaries
    conversations = []
    for tid, data in threads.items():
        messages = data["messages"]

        # Get title from first user message
        first_user_msg = next((m for m in messages if m.role == "user"), None)
        title = "New conversation"
        if first_user_msg:
            content = first_user_msg.content or ""
            title = content[:50] + ("..." if len(content) > 50 else "")

        # Get preview from last message
        last_msg = messages[-1] if messages else None
        preview = ""
        if last_msg:
            content = last_msg.content or ""
            preview = content[:100] + ("..." if len(content) > 100 else "")

        conversations.append({
            "id": tid,
            "title": title,
            "preview": preview,
            "messageCount": len(messages),
            "createdAt": data["created_at"].isoformat(),
            "updatedAt": data["updated_at"].isoformat(),
        })

    # Sort by updated_at descending (most recent first)
    conversations.sort(key=lambda x: x["updatedAt"], reverse=True)

    return conversations


@router.delete("/conversations/{thread_id}")
async def delete_conversation(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation and all its messages."""
    from sqlalchemy import delete

    await db.execute(
        delete(Message).where(Message.thread_id == thread_id)
    )
    await db.commit()

    return {"status": "deleted", "thread_id": thread_id}


@router.get("/{thread_id}/history")
async def get_chat_history(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get chat history for a thread."""
    result = await db.execute(
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


@router.get("/usage/stats")
async def get_usage_stats(
    user_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get rate limit usage statistics for a user.

    Returns:
        - tier: User's tier (free, power, super)
        - unlimited: Whether user has unlimited access
        - requests: Request usage for current minute window
        - tokens: Token usage for current hour window
        - global: System-wide rate limit and queue status
    """
    rate_limiter = get_rate_limiter()
    global_limiter = get_global_rate_limiter()

    # Get user tier
    actual_user_id, tier = await get_user_tier(user_id, db)

    # Get per-user stats
    user_stats = rate_limiter.get_usage_stats(actual_user_id, tier)

    # Get global stats
    global_stats = global_limiter.get_global_stats()

    return {
        **user_stats,
        "global": global_stats,
    }


@router.get("/usage/health")
async def check_rate_limiter_health():
    """Check if rate limiter (Redis) is connected and healthy."""
    rate_limiter = get_rate_limiter()
    global_limiter = get_global_rate_limiter()

    user_connected = rate_limiter.is_connected()
    global_connected = global_limiter.is_connected()

    all_connected = user_connected and global_connected

    return {
        "status": "healthy" if all_connected else "degraded",
        "redis_connected": all_connected,
        "user_rate_limiter": "active" if user_connected else "unavailable",
        "global_rate_limiter": "active" if global_connected else "unavailable",
        "message": "Rate limiting active" if all_connected else "Rate limiting unavailable - requests allowed without limits",
    }


@router.get("/usage/queue")
async def get_queue_status(cleanup: bool = True):
    """Get current queue status.

    Args:
        cleanup: If True (default), automatically remove stale items first

    Returns:
        - queue_size: Number of requests in queue
        - max_queue_size: Maximum queue capacity
        - global_limit: Current global rate limit status
        - stale_removed: Number of stale items removed (if cleanup=True)
    """
    global_limiter = get_global_rate_limiter()

    # Auto-cleanup stale items
    stale_removed = 0
    if cleanup:
        stale_removed = global_limiter.cleanup_stale_items()

    stats = global_limiter.get_global_stats()
    if stale_removed > 0:
        stats["stale_removed"] = stale_removed

    return stats


@router.get("/usage/queue/items")
async def get_queue_items():
    """Get detailed information about items in the queue.

    Returns:
        List of queue items with position, user, message preview, and age.
    """
    global_limiter = get_global_rate_limiter()
    items = global_limiter.get_queue_items()
    return {
        "count": len(items),
        "max_wait_seconds": settings.global_queue_max_wait_seconds,
        "items": items,
    }


@router.post("/usage/queue/cleanup")
async def cleanup_stale_queue_items():
    """Remove stale items from the queue.

    Items older than max_wait_seconds (60s) are considered stale
    because their client connections have likely timed out.

    Returns:
        Number of stale items removed.
    """
    global_limiter = get_global_rate_limiter()
    removed = global_limiter.cleanup_stale_items()
    return {
        "removed": removed,
        "queue_size": global_limiter.get_queue_size(),
    }


@router.delete("/usage/queue/clear")
async def clear_queue():
    """Clear all items from the queue (admin operation).

    Returns:
        Number of items removed.
    """
    global_limiter = get_global_rate_limiter()
    removed = global_limiter.clear_queue()
    return {
        "removed": removed,
        "message": f"Cleared {removed} items from queue",
    }


# =============================================================================
# CACHE ENDPOINTS
# =============================================================================

@router.get("/cache/stats")
async def get_cache_stats():
    """Get cache statistics.

    Returns:
        Cache status and entry count.
    """
    cache_service = get_cache_service()
    return cache_service.get_stats()


@router.delete("/cache/clear")
async def clear_cache(tenant_id: Optional[str] = Query(None)):
    """Clear cache entries.

    Args:
        tenant_id: If provided, only clear entries for this tenant.
                  If not provided, clears all cache entries.

    Returns:
        Number of entries cleared.
    """
    cache_service = get_cache_service()
    removed = cache_service.clear_all(tenant_id=tenant_id)
    return {
        "removed": removed,
        "message": f"Cleared {removed} cache entries" + (f" for tenant {tenant_id}" if tenant_id else ""),
    }


@router.get("/cache/debug/entries")
async def debug_cache_entries(tenant_id: str = Query(...)):
    """Debug endpoint: Get all cache entries for a tenant.

    Shows which entries have embeddings and their metadata.
    """
    cache_service = get_cache_service()
    entries = cache_service.debug_entries(tenant_id)
    return {
        "tenant_id": tenant_id,
        "entry_count": len(entries),
        "entries": entries,
    }


@router.get("/cache/debug/similarity")
async def debug_cache_similarity(
    question: str = Query(...),
    tenant_id: str = Query(...),
):
    """Debug endpoint: Test similarity of a question against cached entries.

    Use this to see what similarity scores your questions get.
    """
    cache_service = get_cache_service()
    return cache_service.test_similarity(question, tenant_id)
