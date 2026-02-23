"""Service for processing documents attached to chat messages."""

import logging
import os
import tempfile
import uuid
from typing import Optional
from pypdf import PdfReader

from ..config import get_settings
from .embedding_service import EmbeddingService

settings = get_settings()
logger = logging.getLogger(__name__)


class DocumentContextService:
    """Service for processing documents for chat context.

    Handles two scenarios:
    1. Small documents (≤5 pages): Extract full text for direct LLM context
    2. Large documents (>5 pages): Embed and perform RAG query
    """

    MAX_PAGES_FOR_FULL_TEXT = 5

    def __init__(self):
        self.embedding_service = EmbeddingService()

    def get_page_count(self, file_path: str) -> int:
        """Get the number of pages in a PDF."""
        try:
            reader = PdfReader(file_path)
            return len(reader.pages)
        except Exception:
            return 0

    def extract_full_text(self, file_path: str) -> str:
        """Extract full text from a PDF using unstructured for better quality."""
        try:
            from unstructured.partition.pdf import partition_pdf

            # Use fast mode for text extraction (no OCR needed for text-based PDFs)
            elements = partition_pdf(
                filename=file_path,
                strategy="fast",
                include_page_breaks=True,
            )

            # Combine all text elements
            text_parts = []
            current_page = 1

            for element in elements:
                # Check for page breaks
                if hasattr(element, 'metadata') and hasattr(element.metadata, 'page_number'):
                    page_num = element.metadata.page_number
                    if page_num and page_num != current_page:
                        text_parts.append(f"\n--- Page {page_num} ---\n")
                        current_page = page_num

                text_parts.append(str(element))

            full_text = "\n".join(text_parts)

            # Fallback to PyPDF2 if unstructured returns empty
            if not full_text.strip():
                return self._extract_with_pypdf(file_path)

            return full_text

        except Exception as e:
            # Fallback to PyPDF2
            return self._extract_with_pypdf(file_path)

    def _extract_with_pypdf(self, file_path: str) -> str:
        """Fallback text extraction using PyPDF2."""
        try:
            reader = PdfReader(file_path)
            text_parts = []

            for i, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                if text.strip():
                    text_parts.append(f"--- Page {i} ---\n{text}")

            return "\n\n".join(text_parts)
        except Exception as e:
            return f"Error extracting text: {str(e)}"

    def embed_and_query(
        self,
        file_path: str,
        filename: str,
        query: str,
        user_id: str,
        tenant_id: str,
        department: str,
        permanent: bool = False,
    ) -> dict:
        """Embed document and perform RAG query.

        Args:
            file_path: Path to the PDF file
            filename: Original filename
            query: User's question to find relevant chunks
            user_id: User ID for ownership
            tenant_id: Tenant ID for isolation
            department: Department for filtering
            permanent: If True, keep in knowledge base. If False, use temp collection.

        Returns:
            dict with context and metadata
        """
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        # Generate a unique document ID for this upload
        doc_id = f"chat_attach_{uuid.uuid4().hex[:8]}"
        doc_name = f"{doc_id}_{filename}"

        # Embed the document
        # Use hi_res for full table/image extraction
        processing_mode = "hi_res" if permanent else "balanced"

        logger.info(f"Starting document embedding: {filename} -> {doc_name}")
        logger.info(f"Processing mode: {processing_mode}, permanent: {permanent}")

        try:
            status, chunks = self.embedding_service.process_document(
                file_path=file_path,
                document_name=doc_name,
                tenant_id=tenant_id,
                department=department,
                access_level="private",  # Chat attachments are private by default
                processing_mode=processing_mode,
                visibility="private" if not permanent else "public",
                user_id=user_id,
            )

            if status.error_message:
                logger.error(f"Embedding error: {status.error_message}")
                return {"error": status.error_message}

            logger.info(f"Document embedded successfully: {len(chunks)} chunks created")

            # Query the embedded document
            client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key,
                timeout=settings.qdrant_timeout,
            )

            # Generate query embedding
            from openai import OpenAI
            openai_client = OpenAI(api_key=settings.openai_api_key)

            query_response = openai_client.embeddings.create(
                model=settings.openai_embedding_model,
                input=query,
            )
            query_vector = query_response.data[0].embedding

            # Search for relevant chunks from this specific document
            results = client.search(
                collection_name=settings.qdrant_collection,
                query_vector=query_vector,
                query_filter=Filter(
                    must=[
                        FieldCondition(key="document_name", match=MatchValue(value=doc_name)),
                        FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    ]
                ),
                limit=5,  # Get top 5 most relevant chunks
                with_payload=True,
            )

            # Build context from results
            context_parts = []
            for i, result in enumerate(results, 1):
                payload = result.payload
                content = payload.get("enhanced_content") or payload.get("content", "")
                page = payload.get("page_number", "?")
                context_parts.append(f"[Chunk {i}, Page {page}]\n{content}")

            context = "\n\n".join(context_parts)

            logger.info(f"RAG query complete: {len(results)} chunks retrieved, context length: {len(context)}")

            # If not permanent, schedule cleanup (or mark for deletion)
            # For now, we'll keep it but mark with visibility=private

            return {
                "context": context,
                "chunks_retrieved": len(results),
                "total_chunks": len(chunks),
                "embedded": True,
                "document_id": doc_name,
            }

        except Exception as e:
            return {"error": f"Failed to embed document: {str(e)}"}

    def process_for_chat(
        self,
        file_path: str,
        filename: str,
        user_id: str,
        tenant_id: str,
        department: str,
        add_to_knowledge_base: bool,
        query: str,
    ) -> dict:
        """Process a document for chat context.

        Args:
            file_path: Path to the PDF file
            filename: Original filename
            user_id: User ID
            tenant_id: Tenant ID
            department: Department
            add_to_knowledge_base: Whether to permanently add to KB
            query: User's question (for RAG if needed)

        Returns:
            dict with:
                - method: "full_text" or "rag"
                - context: The document content or retrieved chunks
                - page_count: Number of pages
                - embedded: Whether document was embedded
                - error: Error message if any
        """
        # Get page count
        page_count = self.get_page_count(file_path)

        if page_count == 0:
            return {"error": "Could not read PDF file"}

        result = {
            "page_count": page_count,
            "embedded": False,
        }

        # Decide processing method
        if page_count <= self.MAX_PAGES_FOR_FULL_TEXT and not add_to_knowledge_base:
            # Small document: extract full text
            result["method"] = "full_text"
            result["context"] = self.extract_full_text(file_path)

        else:
            # Large document OR user wants to add to KB: embed and RAG
            result["method"] = "rag"

            embed_result = self.embed_and_query(
                file_path=file_path,
                filename=filename,
                query=query,
                user_id=user_id,
                tenant_id=tenant_id,
                department=department,
                permanent=add_to_knowledge_base,
            )

            if embed_result.get("error"):
                return {"error": embed_result["error"], "page_count": page_count}

            result["context"] = embed_result.get("context", "")
            result["chunks_retrieved"] = embed_result.get("chunks_retrieved", 0)
            result["embedded"] = embed_result.get("embedded", False)
            result["document_id"] = embed_result.get("document_id")

        return result
