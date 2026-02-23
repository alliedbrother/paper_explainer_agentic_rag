"""Embed House API routes for document processing and embedding."""

import os
import re
import shutil
import tempfile
import urllib.request
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status, BackgroundTasks, Query
from pydantic import BaseModel

from ..services.embedding_service import EmbeddingService, ProcessingStatus
from ..config import get_settings

router = APIRouter(prefix="/embed-house", tags=["embed-house"])

# Simple password auth
EMBED_HOUSE_PASSWORD = "akhilishere"

# In-memory storage for processing jobs (persists during server lifetime)
processing_jobs = {}


class AuthRequest(BaseModel):
    """Password authentication request."""
    password: str


class AuthResponse(BaseModel):
    """Authentication response."""
    authenticated: bool
    message: str


class ProcessingJob(BaseModel):
    """Processing job status."""
    job_id: str
    document_name: str
    status: dict
    chunks: Optional[list] = None


@router.post("/auth", response_model=AuthResponse)
async def authenticate(auth_data: AuthRequest):
    """Authenticate with password."""
    if auth_data.password == EMBED_HOUSE_PASSWORD:
        return AuthResponse(authenticated=True, message="Authentication successful")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid password"
    )


@router.get("/stats")
async def get_collection_stats(password: str):
    """Get Qdrant collection statistics."""
    if password != EMBED_HOUSE_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")

    service = EmbeddingService()
    return service.get_collection_stats()


def status_callback(status: ProcessingStatus):
    """Callback to update job status during processing."""
    # This will be called with the job_id in a closure
    pass


def create_status_callback(job_id: str):
    """Create a callback that updates job status in real-time."""
    def callback(status: ProcessingStatus):
        if job_id in processing_jobs:
            processing_jobs[job_id]["status"] = status.to_dict()
    return callback


def process_document_background(
    job_id: str,
    file_path: str,
    document_name: str,
    tenant_id: str,
    department: str,
    access_level: str,
    processing_mode: str = "hi_res",
    arxiv_id: str = None,
    visibility: str = "public",
    user_id: str = "anonymous"
):
    """Background task to process document."""
    try:
        # Create callback for real-time status updates
        status_callback = create_status_callback(job_id)

        service = EmbeddingService()
        final_status, chunks = service.process_document(
            file_path=file_path,
            document_name=document_name,
            tenant_id=tenant_id,
            department=department,
            access_level=access_level,
            processing_mode=processing_mode,
            status_callback=status_callback,
            arxiv_id=arxiv_id,
            visibility=visibility,
            user_id=user_id
        )

        processing_jobs[job_id]["status"] = final_status.to_dict()
        processing_jobs[job_id]["chunks"] = [c.to_dict() for c in chunks]
        processing_jobs[job_id]["chunks_count"] = len(chunks)
        processing_jobs[job_id]["completed_at"] = datetime.now().isoformat()

    except Exception as e:
        processing_jobs[job_id]["status"]["error_message"] = str(e)
        processing_jobs[job_id]["status"]["logs"] = processing_jobs[job_id]["status"].get("logs", []) + [f"[ERROR] {str(e)}"]
        # Mark current step as error
        for step in ["partitioning", "chunking", "summarization", "vectorization"]:
            if processing_jobs[job_id]["status"].get(step) == "processing":
                processing_jobs[job_id]["status"][step] = "error"
                break

    finally:
        # Clean up temp file (PDF is already stored by embedding_service)
        if os.path.exists(file_path):
            os.remove(file_path)


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    password: str = Form(...),
    tenant_id: str = Form(...),
    department: str = Form(...),
    user_id: str = Form("anonymous"),
    access_level: str = Form("public"),
    visibility: str = Form("public"),  # "public" or "private"
    processing_mode: str = Form("hi_res"),  # fast, balanced, or hi_res
):
    """Upload and process a document.

    Processing modes:
    - fast: Quick text extraction, no OCR, no images (~5-10x faster)
    - balanced: Auto strategy with table inference, no images (~2-3x faster)
    - hi_res: Full OCR, table structure, and image extraction (default, slowest)

    Visibility:
    - public: Visible to all users in same tenant_id + department
    - private: Only visible to the uploaded_by_user_id
    """
    # Verify password
    if password != EMBED_HOUSE_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")

    # Validate file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Validate visibility
    if visibility not in ["public", "private"]:
        raise HTTPException(status_code=400, detail="Visibility must be 'public' or 'private'")

    # Create temp file
    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, file.filename)

    try:
        # Save uploaded file
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Create job ID
        import uuid
        job_id = str(uuid.uuid4())

        # Initialize job status
        initial_status = ProcessingStatus()
        initial_status.upload = "completed"
        initial_status.queued = "processing"

        processing_jobs[job_id] = {
            "job_id": job_id,
            "document_name": file.filename,
            "tenant_id": tenant_id,
            "department": department,
            "user_id": user_id,
            "access_level": access_level,
            "visibility": visibility,
            "processing_mode": processing_mode,
            "created_at": datetime.now().isoformat(),
            "status": initial_status.to_dict(),
            "chunks": None,
            "chunks_count": 0
        }

        # Start background processing
        background_tasks.add_task(
            process_document_background,
            job_id,
            temp_path,
            file.filename,
            tenant_id,
            department,
            access_level,
            processing_mode,
            None,  # arxiv_id
            visibility,
            user_id
        )

        # Update status to queued complete
        processing_jobs[job_id]["status"]["queued"] = "completed"

        return {"job_id": job_id, "message": "Document uploaded and processing started"}

    except Exception as e:
        # Clean up on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/job/{job_id}")
async def get_job_status(job_id: str, password: str):
    """Get processing job status."""
    if password != EMBED_HOUSE_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")

    if job_id not in processing_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    return processing_jobs[job_id]


@router.get("/jobs")
async def list_jobs(password: str):
    """List all processing jobs (summary without chunks data)."""
    if password != EMBED_HOUSE_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")

    # Return job summaries sorted by created_at (newest first)
    job_summaries = []
    for job in processing_jobs.values():
        summary = {
            "job_id": job["job_id"],
            "document_name": job["document_name"],
            "tenant_id": job.get("tenant_id", "unknown"),
            "department": job.get("department", "unknown"),
            "access_level": job.get("access_level", "public"),
            "processing_mode": job.get("processing_mode", "hi_res"),
            "created_at": job.get("created_at"),
            "completed_at": job.get("completed_at"),
            "chunks_count": job.get("chunks_count", 0),
            "is_complete": job["status"].get("vectorization") == "completed",
            "has_error": job["status"].get("error_message") is not None,
        }
        job_summaries.append(summary)

    # Sort by created_at descending
    job_summaries.sort(key=lambda x: x.get("created_at") or "", reverse=True)

    return job_summaries


# =============================================================================
# KNOWLEDGE BASE ENDPOINTS (for chat interface)
# =============================================================================

class ArxivRequest(BaseModel):
    """Request to add arxiv paper."""
    arxiv_id: str
    tenant_id: str = "default"
    department: str = "general"
    processing_mode: str = "fast"
    user_id: str = "anonymous"
    visibility: str = "public"  # "public" or "private"


def extract_arxiv_id(url_or_id: str) -> str:
    """Extract arxiv ID from URL or return as-is if already an ID."""
    # Handle various arxiv URL formats
    patterns = [
        r'arxiv\.org/abs/(\d+\.\d+)',
        r'arxiv\.org/pdf/(\d+\.\d+)',
        r'ar5iv\.labs\.arxiv\.org/html/(\d+\.\d+)',
        r'^(\d+\.\d+)$',  # Just the ID
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return url_or_id  # Return as-is if no pattern matches


def download_arxiv_pdf(arxiv_id: str, temp_dir: str) -> str:
    """Download arxiv PDF to temp directory."""
    import requests

    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    pdf_path = os.path.join(temp_dir, f"{arxiv_id.replace('.', '_')}.pdf")

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    # Try with SSL verification first
    try:
        response = requests.get(pdf_url, headers=headers, timeout=60, verify=True)
        response.raise_for_status()
    except Exception:
        # Fallback: disable SSL verification for environments with cert issues
        response = requests.get(pdf_url, headers=headers, timeout=60, verify=False)
        response.raise_for_status()

    with open(pdf_path, 'wb') as f:
        f.write(response.content)

    return pdf_path


@router.get("/knowledge-base/sources")
async def list_knowledge_sources(
    tenant_id: Optional[str] = None,
    department: Optional[str] = None,
    user_id: Optional[str] = None,
):
    """List all embedded papers/sources in Qdrant with visibility filtering.

    Only returns documents the user has access to:
    - Public docs in their tenant + department
    - Their own private docs
    - Legacy docs (no visibility) in their tenant + department
    """
    from pydantic_settings import BaseSettings
    import os

    settings = get_settings()

    # Debug info
    debug_info = {
        "qdrant_url": settings.qdrant_url,
        "qdrant_collection": settings.qdrant_collection,
        "has_api_key": bool(settings.qdrant_api_key),
        "filters_applied": {
            "tenant_id": tenant_id,
            "department": department,
            "user_id": user_id,
        }
    }

    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    try:
        client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        )

        # Check if collection exists
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]
        debug_info["available_collections"] = collection_names

        if settings.qdrant_collection not in collection_names:
            return {
                "sources": [],
                "total": 0,
                "debug": debug_info,
                "error": f"Collection '{settings.qdrant_collection}' not found"
            }

        # Get collection info
        collection_info = client.get_collection(settings.qdrant_collection)
        try:
            vectors_count = collection_info.points_count
        except AttributeError:
            vectors_count = getattr(collection_info, 'vectors_count', 0)
        debug_info["vectors_count"] = vectors_count

        # Build visibility filter if we have all required params
        scroll_filter = None
        if tenant_id and department and user_id:
            # Full visibility filter
            scroll_filter = Filter(
                should=[  # OR
                    # Public documents in my tenant + department
                    Filter(must=[
                        FieldCondition(key="visibility", match=MatchValue(value="public")),
                        FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                        FieldCondition(key="department", match=MatchValue(value=department)),
                    ]),
                    # My private documents
                    Filter(must=[
                        FieldCondition(key="visibility", match=MatchValue(value="private")),
                        FieldCondition(key="uploaded_by_user_id", match=MatchValue(value=user_id)),
                    ]),
                    # Legacy documents (no visibility field) in my tenant + department
                    Filter(
                        must=[
                            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                            FieldCondition(key="department", match=MatchValue(value=department)),
                        ],
                        must_not=[
                            FieldCondition(key="visibility", match=MatchValue(value="public")),
                            FieldCondition(key="visibility", match=MatchValue(value="private")),
                        ]
                    ),
                ]
            )
            debug_info["visibility_filter"] = "full"
        elif tenant_id:
            # Fallback: just tenant filter
            scroll_filter = Filter(
                must=[FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))]
            )
            debug_info["visibility_filter"] = "tenant_only"
        else:
            debug_info["visibility_filter"] = "none"

        # Scroll through to get unique document names with filter
        results = client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=scroll_filter,
            limit=100,
            with_payload=True,
            with_vectors=False,
        )

        debug_info["scroll_results_count"] = len(results[0]) if results[0] else 0

        # Extract unique sources
        sources_map = {}
        for point in results[0]:
            payload = point.payload or {}
            doc_name = payload.get("document_name") or payload.get("title", "Unknown")
            arxiv_id = payload.get("arxiv_id", "")
            visibility = payload.get("visibility", "public")
            uploaded_by = payload.get("uploaded_by_user_id", "")

            source_key = arxiv_id or doc_name
            if source_key not in sources_map:
                sources_map[source_key] = {
                    "id": source_key,
                    "name": doc_name,
                    "arxiv_id": arxiv_id,
                    "tenant_id": payload.get("tenant_id", "default"),
                    "department": payload.get("department", "general"),
                    "visibility": visibility,
                    "is_own": uploaded_by == user_id if user_id else False,
                    "chunks_count": 1,
                }
            else:
                sources_map[source_key]["chunks_count"] += 1

        return {
            "sources": list(sources_map.values()),
            "total": len(sources_map),
            "collection": settings.qdrant_collection,
            "vectors_count": vectors_count,
            "debug": debug_info,
        }

    except Exception as e:
        import traceback
        return {
            "sources": [],
            "total": 0,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "debug": debug_info,
        }


@router.get("/knowledge-base/document/{document_id}/chunks")
async def get_document_chunks(document_id: str, tenant_id: Optional[str] = None):
    """Get all chunks for a specific document.

    document_id can be either arxiv_id or document_name.
    Returns chunks with content, enhanced_content, images, tables, etc.
    """
    settings = get_settings()
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    try:
        client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        )

        # Check if collection exists
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]

        if settings.qdrant_collection not in collection_names:
            return {"chunks": [], "document_name": document_id, "chunks_count": 0}

        # Build filter - match either arxiv_id or document_name
        filter_conditions = Filter(
            should=[
                FieldCondition(key="arxiv_id", match=MatchValue(value=document_id)),
                FieldCondition(key="document_name", match=MatchValue(value=document_id)),
            ]
        )

        # Scroll through all matching points
        chunks = []
        document_name = document_id
        arxiv_id = None
        offset = None

        while True:
            results, offset = client.scroll(
                collection_name=settings.qdrant_collection,
                scroll_filter=filter_conditions,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )

            for point in results:
                payload = point.payload or {}
                # Get document name from first chunk
                if document_name == document_id:
                    document_name = payload.get("document_name") or payload.get("title") or document_id
                if not arxiv_id:
                    arxiv_id = payload.get("arxiv_id")

                chunks.append({
                    "chunk_id": payload.get("chunk_id") or str(point.id),
                    "content": payload.get("content", ""),
                    "enhanced_content": payload.get("enhanced_content", ""),
                    "page_number": payload.get("page_number", 1),
                    "char_count": payload.get("char_count", len(payload.get("content", ""))),
                    "content_types": payload.get("content_types", ["text"]),
                    "tables_html": payload.get("tables_html", []),
                    "images_base64": payload.get("images_base64", []),
                    "visibility": payload.get("visibility", "public"),
                    "uploaded_by_user_id": payload.get("uploaded_by_user_id"),
                })

            if offset is None:
                break

        # Sort by page number
        chunks.sort(key=lambda x: x.get("page_number", 0))

        return {
            "document_name": document_name,
            "document_id": document_id,
            "arxiv_id": arxiv_id,
            "chunks_count": len(chunks),
            "chunks": chunks,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/knowledge-base/document/{document_id}")
async def delete_document(
    document_id: str,
    tenant_id: str = Query(...),
    user_id: str = Query(...),
):
    """Delete a document from the knowledge base.

    Only the owner (uploaded_by_user_id) can delete a document.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    settings = get_settings()

    client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=settings.qdrant_timeout,
    )

    # Build filter to find document by document_name or arxiv_id
    doc_filter = Filter(
        should=[
            Filter(must=[FieldCondition(key="document_name", match=MatchValue(value=document_id))]),
            Filter(must=[FieldCondition(key="arxiv_id", match=MatchValue(value=document_id))]),
        ]
    )

    # First, check if document exists and verify ownership
    try:
        results = client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=doc_filter,
            limit=1,
            with_payload=["uploaded_by_user_id", "document_name"],
        )

        points, _ = results
        if not points:
            raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found")

        # Check ownership
        owner = points[0].payload.get("uploaded_by_user_id")
        if owner and owner != user_id:
            raise HTTPException(status_code=403, detail="You don't have permission to delete this document")

        # Delete all points for this document
        client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=doc_filter,
        )

        return {
            "success": True,
            "document_id": document_id,
            "message": "Document deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")


@router.get("/knowledge-base/check/{arxiv_id}")
async def check_arxiv_exists(arxiv_id: str):
    """Check if an arxiv paper is already embedded."""
    settings = get_settings()
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    clean_id = extract_arxiv_id(arxiv_id)

    try:
        client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        )

        # Check if collection exists
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]

        if settings.qdrant_collection not in collection_names:
            return {"exists": False, "arxiv_id": clean_id}

        # Search for documents with this arxiv_id
        results = client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="arxiv_id", match=MatchValue(value=clean_id))]
            ),
            limit=1,
            with_payload=True,
        )

        exists = len(results[0]) > 0
        return {
            "exists": exists,
            "arxiv_id": clean_id,
            "chunks_count": len(results[0]) if exists else 0,
        }

    except Exception as e:
        return {"exists": False, "arxiv_id": clean_id, "error": str(e)}


@router.post("/knowledge-base/add-arxiv")
async def add_arxiv_paper(
    background_tasks: BackgroundTasks,
    request: ArxivRequest,
):
    """Add an arxiv paper to the knowledge base."""
    clean_id = extract_arxiv_id(request.arxiv_id)

    # Check if already exists
    check_result = await check_arxiv_exists(clean_id)
    if check_result.get("exists"):
        return {
            "status": "already_exists",
            "arxiv_id": clean_id,
            "message": f"Paper {clean_id} is already embedded with {check_result.get('chunks_count', 0)} chunks",
        }

    # Download the PDF
    temp_dir = tempfile.mkdtemp()
    try:
        pdf_path = download_arxiv_pdf(clean_id, temp_dir)
    except Exception as e:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise HTTPException(status_code=400, detail=f"Failed to download arxiv paper: {str(e)}")

    # Create job ID
    import uuid
    job_id = str(uuid.uuid4())

    # Initialize job status
    initial_status = ProcessingStatus()
    initial_status.upload = "completed"
    initial_status.queued = "processing"

    document_name = f"arxiv_{clean_id}.pdf"

    processing_jobs[job_id] = {
        "job_id": job_id,
        "document_name": document_name,
        "arxiv_id": clean_id,
        "tenant_id": request.tenant_id,
        "department": request.department,
        "user_id": request.user_id,
        "access_level": "public",
        "visibility": request.visibility,
        "processing_mode": request.processing_mode,
        "created_at": datetime.now().isoformat(),
        "status": initial_status.to_dict(),
        "chunks": None,
        "chunks_count": 0
    }

    # Start background processing
    background_tasks.add_task(
        process_document_background,
        job_id,
        pdf_path,
        document_name,
        request.tenant_id,
        request.department,
        "public",
        request.processing_mode,
        clean_id,  # arxiv_id
        request.visibility,
        request.user_id
    )

    # Update status to queued complete
    processing_jobs[job_id]["status"]["queued"] = "completed"

    return {
        "status": "processing",
        "job_id": job_id,
        "arxiv_id": clean_id,
        "message": f"Started embedding arxiv paper {clean_id}",
    }
