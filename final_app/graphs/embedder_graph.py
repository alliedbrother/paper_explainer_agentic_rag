"""Document embedder subgraph."""

from typing import Optional

from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from ..config import get_settings
from .state import EmbedderState

settings = get_settings()


def build_embedder_subgraph():
    """Build the document embedder subgraph.

    Flow:
        check_arxiv → check_db ┬→ (if exists) → notify_ready → END
                               └→ (if not) → embed_document ─┬→ notify_user
                                                              └→ create_webpage → upload_s3

    Returns:
        Compiled subgraph
    """

    def check_arxiv_format(state: EmbedderState) -> dict:
        """Check if input is an arXiv paper and extract ID."""
        import re

        arxiv_id = state.get("arxiv_id")
        doc_path = state.get("document_path")

        if arxiv_id:
            # Already have arxiv_id
            return {"is_arxiv": True}

        if doc_path:
            # Check if path contains arXiv ID pattern
            # Patterns: 1234.56789, arxiv:1234.56789, etc.
            match = re.search(r"(\d{4}\.\d{4,5})", doc_path)
            if match:
                return {"arxiv_id": match.group(1), "is_arxiv": True}

            # Check URL pattern
            match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", doc_path)
            if match:
                return {"arxiv_id": match.group(1), "is_arxiv": True}

        return {"is_arxiv": False}

    def check_database(state: EmbedderState) -> dict:
        """Check if paper already exists in database."""
        # TODO: Actually query PostgreSQL
        # For now, assume not exists
        return {"exists_in_db": False}

    def route_after_db_check(state: EmbedderState) -> str:
        """Route based on database check."""
        if state.get("exists_in_db"):
            return "notify_ready"
        return "embed_document"

    def notify_ready(state: EmbedderState) -> dict:
        """Notify user that paper is ready for RAG."""
        return {
            "embedding_status": "completed",
        }

    def embed_document(state: EmbedderState) -> dict:
        """Embed the document into vector store."""
        # TODO: Implement actual embedding
        # 1. Fetch paper (from arXiv or local)
        # 2. Extract text and images (unstructured)
        # 3. Chunk text
        # 4. Generate embeddings
        # 5. Store in Qdrant
        # 6. Store metadata in PostgreSQL

        return {
            "embedding_status": "completed",
            "chunks": [],  # Placeholder
            "paper_metadata": {
                "title": f"Paper {state.get('arxiv_id', 'unknown')}",
                "authors": [],
                "abstract": "",
            },
        }

    def route_parallel(state: EmbedderState) -> list[Send]:
        """Route to parallel branches after embedding."""
        return [
            Send("notify_user", state),
            Send("create_webpage", state),
        ]

    def notify_user(state: EmbedderState) -> dict:
        """Notify user that embedding is complete."""
        # This would trigger a notification
        return {}

    def create_webpage(state: EmbedderState) -> dict:
        """Create paper webpage/blog."""
        # TODO: Implement with deep agent
        # 1. Analyze paper content
        # 2. Generate HTML with:
        #    - Summary, key contributions
        #    - Methodology explanation
        #    - Pros/cons analysis
        #    - Images from paper
        # 3. Store webpage content

        html_content = f"""
        <html>
        <head><title>{state.get('paper_metadata', {}).get('title', 'Paper')}</title></head>
        <body>
            <h1>{state.get('paper_metadata', {}).get('title', 'Paper')}</h1>
            <p>[Webpage content placeholder]</p>
        </body>
        </html>
        """
        return {"webpage_content": html_content}

    def upload_to_s3(state: EmbedderState) -> dict:
        """Upload webpage to S3."""
        # TODO: Implement S3 upload
        arxiv_id = state.get("arxiv_id", "unknown")
        s3_url = f"https://{settings.s3_bucket}.s3.amazonaws.com/paperblog/{arxiv_id}"
        return {"s3_url": s3_url}

    # Build graph
    builder = StateGraph(EmbedderState)

    # Add nodes
    builder.add_node("check_arxiv", check_arxiv_format)
    builder.add_node("check_db", check_database)
    builder.add_node("notify_ready", notify_ready)
    builder.add_node("embed_document", embed_document)
    builder.add_node("notify_user", notify_user)
    builder.add_node("create_webpage", create_webpage)
    builder.add_node("upload_s3", upload_to_s3)

    # Add edges
    builder.add_edge(START, "check_arxiv")
    builder.add_edge("check_arxiv", "check_db")
    builder.add_conditional_edges(
        "check_db",
        route_after_db_check,
        {
            "notify_ready": "notify_ready",
            "embed_document": "embed_document",
        },
    )
    builder.add_edge("notify_ready", END)

    # After embedding, go to parallel branches
    # Note: For true parallelism, would need Send() but simplified here
    builder.add_edge("embed_document", "notify_user")
    builder.add_edge("embed_document", "create_webpage")
    builder.add_edge("notify_user", END)
    builder.add_edge("create_webpage", "upload_s3")
    builder.add_edge("upload_s3", END)

    return builder.compile()


# Tool wrapper for main agent
@tool
def document_embedder(
    arxiv_id: str,
) -> str:
    """Embed an arXiv paper into the RAG system.

    This tool:
    1. Checks if the paper is already embedded for the current tenant/department
    2. If not: downloads the PDF from arXiv
    3. Stores the PDF locally
    4. Embeds the document into the vector database
    5. Makes it available for RAG queries

    The user's tenant_id, department, and user_id are automatically determined from context.

    Args:
        arxiv_id: arXiv paper ID (e.g., "1706.03762") or arXiv URL

    Returns:
        Embedding status and paper info
    """
    import os
    import re
    import tempfile
    import shutil
    import urllib.request
    from pathlib import Path

    from ..services.progress_tracker import (
        get_current_user_id,
        get_current_tenant_id,
        get_current_department,
        get_current_thread_id,
        get_progress_tracker,
    )
    from ..services.embedding_service import EmbeddingService, ProcessingStatus
    from ..config import get_settings

    settings = get_settings()
    tracker = get_progress_tracker()
    thread_id = get_current_thread_id()

    # Get user context
    user_id = get_current_user_id() or "anonymous"
    tenant_id = get_current_tenant_id() or "default"
    department = get_current_department() or "general"

    # Extract clean arXiv ID from URL if needed
    def extract_arxiv_id(url_or_id: str) -> str:
        patterns = [
            r'arxiv\.org/abs/(\d+\.\d+)',
            r'arxiv\.org/pdf/(\d+\.\d+)',
            r'ar5iv\.labs\.arxiv\.org/html/(\d+\.\d+)',
            r'^(\d+\.\d+)$',
        ]
        for pattern in patterns:
            match = re.search(pattern, url_or_id)
            if match:
                return match.group(1)
        return url_or_id

    clean_id = extract_arxiv_id(arxiv_id)
    pdf_filename = f"arxiv_{clean_id.replace('.', '_')}.pdf"

    # Start progress tracking
    if thread_id:
        tracker.start_embedding(thread_id, pdf_filename, clean_id)
        tracker.update_embedding(
            thread_id,
            step="download",
            status="processing",
            message="Checking if paper exists...",
            log_message=f"arXiv ID: {clean_id}"
        )

    # Check if paper already exists in Qdrant for this tenant/department
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        )

        # Check if collection exists
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]

        if settings.qdrant_collection in collection_names:
            # Search for documents with this arxiv_id in this tenant/department
            results = client.scroll(
                collection_name=settings.qdrant_collection,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(key="arxiv_id", match=MatchValue(value=clean_id)),
                        FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                        FieldCondition(key="department", match=MatchValue(value=department)),
                    ]
                ),
                limit=1,
                with_payload=True,
            )

            if len(results[0]) > 0:
                # Paper already exists
                payload = results[0][0].payload
                doc_name = payload.get("document_name", f"arxiv_{clean_id}")
                if thread_id:
                    tracker.update_embedding(
                        thread_id,
                        step="download",
                        status="completed",
                        message="Paper already exists",
                        log_message=f"Paper already embedded in {tenant_id}/{department}"
                    )
                    tracker.complete_embedding(thread_id)
                return (
                    f"**Paper Already Embedded**\n\n"
                    f"arXiv ID: `{clean_id}`\n"
                    f"Document: {doc_name}\n"
                    f"Tenant: {tenant_id}\n"
                    f"Department: {department}\n\n"
                    f"This paper is already in your knowledge base and ready for RAG queries!"
                )

    except Exception as e:
        if thread_id:
            tracker.update_embedding(thread_id, log_message=f"DB check warning: {str(e)[:50]}")
        # Continue to embedding if check fails
        pass

    # Download the PDF from arXiv
    if thread_id:
        tracker.update_embedding(
            thread_id,
            step="download",
            status="processing",
            message="Downloading PDF from arXiv...",
            log_message=f"Downloading: https://arxiv.org/pdf/{clean_id}.pdf"
        )

    pdf_url = f"https://arxiv.org/pdf/{clean_id}.pdf"
    temp_dir = tempfile.mkdtemp()

    try:
        temp_pdf_path = os.path.join(temp_dir, pdf_filename)

        # Try downloading with requests first (better SSL handling), fallback to urllib
        try:
            import requests
            response = requests.get(
                pdf_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                timeout=60,
                verify=True  # Try with verification first
            )
            response.raise_for_status()
            with open(temp_pdf_path, 'wb') as f:
                f.write(response.content)
        except Exception:
            # Fallback: try with SSL verification disabled (for environments with cert issues)
            try:
                import requests
                response = requests.get(
                    pdf_url,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                    timeout=60,
                    verify=False  # Disable SSL verification as fallback
                )
                response.raise_for_status()
                with open(temp_pdf_path, 'wb') as f:
                    f.write(response.content)
            except Exception as download_error:
                if thread_id:
                    tracker.update_embedding(
                        thread_id,
                        step="download",
                        status="error",
                        message=f"Download failed: {str(download_error)[:50]}",
                        log_message=f"ERROR: {str(download_error)}"
                    )
                    tracker.complete_embedding(thread_id, success=False, error=str(download_error))
                return f"**Error Downloading Paper**\n\nFailed to download arXiv paper `{clean_id}`:\n{str(download_error)}\n\nTry uploading the PDF manually via the Embed House UI."

        # Get file size
        file_size = os.path.getsize(temp_pdf_path) / (1024 * 1024)  # MB
        if thread_id:
            tracker.update_embedding(
                thread_id,
                step="download",
                status="completed",
                message="PDF downloaded successfully",
                log_message=f"Downloaded: {file_size:.1f} MB"
            )

        # Store the PDF locally (similar to uploaded docs)
        storage_dir = Path(settings.pdf_storage_dir) / tenant_id / department / user_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        stored_pdf_path = storage_dir / pdf_filename
        shutil.copy2(temp_pdf_path, stored_pdf_path)

        if thread_id:
            tracker.update_embedding(
                thread_id,
                log_message=f"Stored PDF at: {stored_pdf_path}"
            )

        # Create a status callback that updates our progress tracker
        def status_callback(status: ProcessingStatus):
            if not thread_id:
                return

            # Map ProcessingStatus to our progress tracker
            if status.partitioning == "processing":
                tracker.update_embedding(
                    thread_id,
                    step="partition",
                    status="processing",
                    message=status.progress_message or "Partitioning PDF...",
                )
            elif status.partitioning == "completed":
                tracker.update_embedding(
                    thread_id,
                    step="partition",
                    status="completed",
                    elements_extracted=status.atomic_elements,
                    log_message=f"Extracted {status.atomic_elements} elements"
                )

            if status.chunking == "processing":
                tracker.update_embedding(
                    thread_id,
                    step="chunking",
                    status="processing",
                    message=status.progress_message or "Creating chunks...",
                )
            elif status.chunking == "completed":
                tracker.update_embedding(
                    thread_id,
                    step="chunking",
                    status="completed",
                    total_chunks=status.chunks_created,
                    log_message=f"Created {status.chunks_created} chunks"
                )

            if status.summarization == "processing":
                tracker.update_embedding(
                    thread_id,
                    step="summarization",
                    status="processing",
                    message=status.progress_message or "Summarizing chunks...",
                    current_chunk=status.current_chunk,
                    total_chunks=status.total_chunks,
                )
                if status.current_chunk > 0 and status.current_chunk % 5 == 0:
                    tracker.update_embedding(
                        thread_id,
                        log_message=f"Summarized {status.current_chunk}/{status.total_chunks} chunks"
                    )
            elif status.summarization == "completed":
                tracker.update_embedding(
                    thread_id,
                    step="summarization",
                    status="completed",
                    log_message="Summarization complete"
                )

            if status.vectorization == "processing":
                tracker.update_embedding(
                    thread_id,
                    step="vectorization",
                    status="processing",
                    message=status.progress_message or "Storing vectors...",
                )
            elif status.vectorization == "completed":
                tracker.update_embedding(
                    thread_id,
                    step="vectorization",
                    status="completed",
                    log_message="Vectors stored in Qdrant"
                )

            # Log any new log entries from status
            if status.logs:
                last_log = status.logs[-1] if status.logs else None
                if last_log and "Page" in last_log:
                    # Extract page progress from log
                    tracker.update_embedding(thread_id, log_message=last_log.split("] ")[-1] if "] " in last_log else last_log)

        # Start embedding
        if thread_id:
            tracker.update_embedding(
                thread_id,
                step="partition",
                status="processing",
                message="Starting PDF partitioning (hi_res mode)...",
                log_message="Processing mode: HI_RES (full OCR, tables, images)"
            )

        # Embed the document
        service = EmbeddingService()
        final_status, chunks = service.process_document(
            file_path=str(temp_pdf_path),
            document_name=pdf_filename,
            tenant_id=tenant_id,
            department=department,
            access_level="public",
            processing_mode="hi_res",  # Full OCR, tables, and image extraction
            status_callback=status_callback,
            arxiv_id=clean_id,
            visibility="public",
            user_id=user_id,
        )

        # Check for errors
        if final_status.error_message:
            if thread_id:
                tracker.complete_embedding(thread_id, success=False, error=final_status.error_message)
            return (
                f"**Embedding Error**\n\n"
                f"arXiv ID: `{clean_id}`\n"
                f"Error: {final_status.error_message}\n\n"
                f"Please try again or use the Embed House UI for more details."
            )

        # Success
        if thread_id:
            tracker.update_embedding(
                thread_id,
                log_message=f"Successfully embedded {len(chunks)} chunks"
            )
            tracker.complete_embedding(thread_id, success=True)

        return (
            f"**Paper Successfully Embedded!**\n\n"
            f"arXiv ID: `{clean_id}`\n"
            f"Document: {pdf_filename}\n"
            f"Chunks created: {len(chunks)}\n"
            f"Elements extracted: {final_status.atomic_elements}\n"
            f"Tenant: {tenant_id}\n"
            f"Department: {department}\n"
            f"Stored at: `{stored_pdf_path}`\n\n"
            f"The paper is now available for RAG queries. Try asking questions about it!"
        )

    except Exception as e:
        if thread_id:
            tracker.complete_embedding(thread_id, success=False, error=str(e))
        return f"**Embedding Failed**\n\narXiv ID: `{clean_id}`\nError: {str(e)}"

    finally:
        # Clean up temp directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


document_embedder_tool = document_embedder
