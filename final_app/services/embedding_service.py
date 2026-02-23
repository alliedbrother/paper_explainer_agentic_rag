"""Document embedding service using Unstructured.io and Qdrant."""

import json
import uuid
import logging
import tempfile
import os
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import HumanMessage
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, HnswConfigDiff, PayloadSchemaType
from pypdf import PdfReader, PdfWriter

from ..config import get_settings

settings = get_settings()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ProcessingStatus:
    """Track processing pipeline status."""
    upload: str = "pending"  # pending, processing, completed, error
    queued: str = "pending"
    partitioning: str = "pending"
    chunking: str = "pending"
    summarization: str = "pending"
    vectorization: str = "pending"

    # Stats
    elements_discovered: Dict[str, int] = field(default_factory=dict)
    chunks_created: int = 0
    atomic_elements: int = 0
    avg_chunk_size: int = 0

    # Progress tracking
    current_step: str = ""
    current_chunk: int = 0
    total_chunks: int = 0
    progress_message: str = ""
    logs: List[str] = field(default_factory=list)

    # Error tracking
    error_message: Optional[str] = None

    def log(self, message: str):
        """Add a log message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)
        logger.info(message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "upload": self.upload,
            "queued": self.queued,
            "partitioning": self.partitioning,
            "chunking": self.chunking,
            "summarization": self.summarization,
            "vectorization": self.vectorization,
            "elements_discovered": self.elements_discovered,
            "chunks_created": self.chunks_created,
            "atomic_elements": self.atomic_elements,
            "avg_chunk_size": self.avg_chunk_size,
            "current_step": self.current_step,
            "current_chunk": self.current_chunk,
            "total_chunks": self.total_chunks,
            "progress_message": self.progress_message,
            "logs": self.logs[-20:],  # Last 20 logs
            "error_message": self.error_message,
        }


@dataclass
class ProcessedChunk:
    """A processed document chunk."""
    chunk_id: str
    content: str
    enhanced_content: str
    page_number: int
    char_count: int
    content_types: List[str]
    tables_html: List[str]
    images_base64: List[str]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "enhanced_content": self.enhanced_content,  # Full content for display
            "page_number": self.page_number,
            "char_count": self.char_count,
            "content_types": self.content_types,
            "tables_html": self.tables_html,  # Include tables for display
            "images_base64": self.images_base64[:3] if self.images_base64 else [],  # Limit to 3 images
            "has_tables": len(self.tables_html) > 0,
            "has_images": len(self.images_base64) > 0,
        }


class EmbeddingService:
    """Service for processing and embedding documents into Qdrant."""

    COLLECTION_NAME = "research_papers"
    VECTOR_SIZE = 1536  # OpenAI text-embedding-3-small

    def __init__(self):
        self._qdrant_client = None
        self._embeddings = None
        self._llm = None

    def _get_qdrant_client(self) -> QdrantClient:
        """Get or create Qdrant client."""
        if self._qdrant_client is None:
            if not settings.qdrant_url:
                raise ValueError("QDRANT_URL is required")
            if not settings.qdrant_api_key:
                raise ValueError("QDRANT_API_KEY is required")

            self._qdrant_client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key
            )
        return self._qdrant_client

    def _get_embeddings(self) -> OpenAIEmbeddings:
        """Get or create embeddings model."""
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small",
                openai_api_key=settings.openai_api_key
            )
        return self._embeddings

    def _get_llm(self) -> ChatOpenAI:
        """Get or create LLM for summarization."""
        if self._llm is None:
            self._llm = ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0,
                openai_api_key=settings.openai_api_key
            )
        return self._llm

    def ensure_collection_exists(self, status: ProcessingStatus):
        """Ensure Qdrant collection exists with proper schema and indexes."""
        status.log(f"Checking if Qdrant collection '{self.COLLECTION_NAME}' exists...")
        client = self._get_qdrant_client()

        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]

        if self.COLLECTION_NAME not in collection_names:
            status.log(f"Creating new collection: {self.COLLECTION_NAME}")
            client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=self.VECTOR_SIZE,
                    distance=Distance.COSINE
                ),
                hnsw_config=HnswConfigDiff(
                    m=16,              # Number of edges per node (good for <1M docs)
                    ef_construct=128,  # Build-time accuracy (slightly lower for faster indexing)
                    full_scan_threshold=10000,  # Use brute force below this
                ),
            )
            status.log(f"Collection '{self.COLLECTION_NAME}' created successfully with HNSW config")
            # Create payload indexes for the new collection
            self._create_payload_indexes(client, status)
        else:
            status.log(f"Collection '{self.COLLECTION_NAME}' already exists")

        return True

    def _create_payload_indexes(self, client: QdrantClient, status: ProcessingStatus):
        """Create indexes for frequently filtered fields."""
        indexes = [
            ("tenant_id", PayloadSchemaType.KEYWORD),
            ("department", PayloadSchemaType.KEYWORD),
            ("visibility", PayloadSchemaType.KEYWORD),
            ("uploaded_by_user_id", PayloadSchemaType.KEYWORD),
            ("arxiv_id", PayloadSchemaType.KEYWORD),
            ("document_name", PayloadSchemaType.KEYWORD),
        ]

        for field_name, field_type in indexes:
            try:
                client.create_payload_index(
                    collection_name=self.COLLECTION_NAME,
                    field_name=field_name,
                    field_schema=field_type,
                )
                status.log(f"Created payload index: {field_name}")
            except Exception as e:
                # Index may already exist
                status.log(f"Index {field_name} may already exist: {e}")

    def _store_pdf(
        self,
        source_path: str,
        document_name: str,
        tenant_id: str,
        department: str,
        user_id: str = "anonymous"
    ) -> str:
        """Store PDF locally, organized by tenant/department/user.

        Args:
            source_path: Path to the source PDF file
            document_name: Name of the document
            tenant_id: Tenant identifier
            department: Department name
            user_id: User who uploaded the document

        Returns:
            Path to the stored PDF file
        """
        storage_dir = Path(settings.pdf_storage_dir) / tenant_id / department / user_id
        storage_dir.mkdir(parents=True, exist_ok=True)

        dest_path = storage_dir / document_name
        shutil.copy2(source_path, dest_path)
        logger.info(f"Stored PDF at: {dest_path}")
        return str(dest_path)

    MAX_PAGES = 12  # Limit processing to first 12 pages
    MAX_PARALLEL_WORKERS = 8  # Number of parallel workers for partitioning (increased from 4)

    def _extract_first_n_pages(self, file_path: str, n_pages: int, status: ProcessingStatus) -> Tuple[str, int]:
        """Extract first N pages from PDF to a temporary file.

        Returns tuple of (temp_file_path, actual_page_count).
        """
        reader = PdfReader(file_path)
        total_pages = len(reader.pages)
        pages_to_extract = min(n_pages, total_pages)

        status.log(f"PDF has {total_pages} pages, extracting first {pages_to_extract} pages")

        if total_pages <= n_pages:
            # If PDF has fewer pages than limit, use original file
            return file_path, total_pages

        # Create a new PDF with only first N pages
        writer = PdfWriter()
        for i in range(pages_to_extract):
            writer.add_page(reader.pages[i])

        # Write to temp file
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, f"first_{pages_to_extract}_pages.pdf")
        with open(temp_path, "wb") as f:
            writer.write(f)

        status.log(f"Created temporary PDF with {pages_to_extract} pages: {temp_path}")
        return temp_path, pages_to_extract

    def _partition_page_range(self, file_path: str, start_page: int, end_page: int) -> List[Any]:
        """Partition a specific range of pages from a PDF."""
        from unstructured.partition.pdf import partition_pdf

        # partition_pdf uses 1-based page numbers
        elements = partition_pdf(
            filename=file_path,
            strategy="hi_res",
            infer_table_structure=True,
            extract_image_block_types=["Image"],
            extract_image_block_to_payload=True,
            starting_page_number=start_page,
            # Only process pages in this range
        )

        # Filter elements to only include those from the specified page range
        filtered_elements = []
        for el in elements:
            if hasattr(el, 'metadata') and hasattr(el.metadata, 'page_number'):
                page_num = el.metadata.page_number
                if page_num is not None and start_page <= page_num <= end_page:
                    filtered_elements.append(el)
            else:
                # Include elements without page info
                filtered_elements.append(el)

        return filtered_elements

    def _partition_single_page(self, args: Tuple[str, int, str]) -> Tuple[int, List[Any]]:
        """Partition a single page from a PDF. Returns (page_number, elements).

        Args:
            args: Tuple of (file_path, page_num, processing_mode)
                  processing_mode: 'fast', 'balanced', or 'hi_res'
        """
        from unstructured.partition.pdf import partition_pdf

        file_path, page_num, processing_mode = args

        try:
            # Extract just this page to a temp file for processing
            reader = PdfReader(file_path)
            writer = PdfWriter()
            writer.add_page(reader.pages[page_num - 1])  # page_num is 1-indexed

            temp_dir = tempfile.mkdtemp()
            temp_path = os.path.join(temp_dir, f"page_{page_num}.pdf")
            with open(temp_path, "wb") as f:
                writer.write(f)

            try:
                # Configure based on processing mode
                if processing_mode == 'fast':
                    # Fast mode: quick extraction, no OCR, no image extraction
                    elements = partition_pdf(
                        filename=temp_path,
                        strategy="fast",
                        infer_table_structure=False,
                    )
                elif processing_mode == 'balanced':
                    # Balanced: auto strategy with table inference but no images
                    elements = partition_pdf(
                        filename=temp_path,
                        strategy="auto",
                        infer_table_structure=True,
                    )
                else:  # hi_res
                    # High quality: full OCR, table structure, image extraction
                    elements = partition_pdf(
                        filename=temp_path,
                        strategy="hi_res",
                        infer_table_structure=True,
                        extract_image_block_types=["Image"],
                        extract_image_block_to_payload=True
                    )

                # Update page numbers in metadata to reflect original page
                for el in elements:
                    if hasattr(el, 'metadata'):
                        el.metadata.page_number = page_num

                return (page_num, elements)
            finally:
                # Clean up temp file
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)

        except Exception as e:
            logger.error(f"Error partitioning page {page_num}: {e}")
            return (page_num, [])

    def partition_document(
        self,
        file_path: str,
        status: ProcessingStatus,
        update_status: callable = None,
        processing_mode: str = "hi_res"
    ) -> List[Any]:
        """Extract elements from PDF using unstructured with parallel processing.

        Processes first MAX_PAGES pages in parallel for faster extraction.

        Args:
            file_path: Path to the PDF file
            status: ProcessingStatus object for tracking progress
            update_status: Callback function for status updates
            processing_mode: 'fast', 'balanced', or 'hi_res'
                - fast: Quick text extraction, no OCR, no images (~5-10x faster)
                - balanced: Auto strategy with tables, no images (~2-3x faster)
                - hi_res: Full OCR, tables, and image extraction (default)
        """
        from unstructured.partition.pdf import partition_pdf

        status.partitioning = "processing"
        status.current_step = "partitioning"
        status.progress_message = "Extracting text, images, and tables from PDF..."
        status.log(f"Starting PDF partitioning: {file_path}")
        status.log(f"Processing mode: {processing_mode.upper()}")
        status.log(f"Processing limit: first {self.MAX_PAGES} pages with {self.MAX_PARALLEL_WORKERS} parallel workers")

        mode_descriptions = {
            'fast': "Fast mode: text extraction only, no OCR or images",
            'balanced': "Balanced mode: auto strategy with table inference",
            'hi_res': "Hi-res mode: full OCR, table structure, and image extraction"
        }
        status.log(mode_descriptions.get(processing_mode, mode_descriptions['hi_res']))
        if update_status:
            update_status()

        try:
            # Get page count and limit to MAX_PAGES
            reader = PdfReader(file_path)
            total_pages = len(reader.pages)
            pages_to_process = min(self.MAX_PAGES, total_pages)

            status.log(f"PDF has {total_pages} pages, will process {pages_to_process} pages")
            if update_status:
                update_status()

            # Prepare page tasks (1-indexed page numbers) with processing mode
            page_tasks = [(file_path, i, processing_mode) for i in range(1, pages_to_process + 1)]

            # Process pages in parallel
            all_elements = []
            completed_pages = 0

            status.log(f"Starting parallel processing of {pages_to_process} pages with {self.MAX_PARALLEL_WORKERS} workers...")
            if update_status:
                update_status()

            with ThreadPoolExecutor(max_workers=self.MAX_PARALLEL_WORKERS) as executor:
                # Submit all tasks
                future_to_page = {
                    executor.submit(self._partition_single_page, task): task[1]
                    for task in page_tasks
                }

                # Collect results as they complete
                page_results = {}
                for future in as_completed(future_to_page):
                    page_num = future_to_page[future]
                    try:
                        result_page, elements = future.result()
                        page_results[result_page] = elements
                        completed_pages += 1
                        status.log(f"  Page {result_page}/{pages_to_process}: {len(elements)} elements extracted")
                        status.progress_message = f"Partitioning: {completed_pages}/{pages_to_process} pages done"
                        if update_status:
                            update_status()
                    except Exception as e:
                        status.log(f"  Page {page_num}: ERROR - {str(e)}")
                        completed_pages += 1
                        if update_status:
                            update_status()

            # Combine elements in page order
            for page_num in sorted(page_results.keys()):
                all_elements.extend(page_results[page_num])

            status.log(f"PDF partitioning complete. Found {len(all_elements)} elements from {pages_to_process} pages")
            if update_status:
                update_status()

            # Count element types
            type_counts = {}
            for el in all_elements:
                el_type = type(el).__name__
                type_counts[el_type] = type_counts.get(el_type, 0) + 1

            # Log element types found
            for el_type, count in type_counts.items():
                status.log(f"  - {el_type}: {count}")

            status.elements_discovered = {
                "text_sections": type_counts.get("NarrativeText", 0) + type_counts.get("Text", 0),
                "tables": type_counts.get("Table", 0),
                "images": type_counts.get("Image", 0),
                "titles_headers": type_counts.get("Title", 0) + type_counts.get("Header", 0),
                "other_elements": sum(v for k, v in type_counts.items()
                                     if k not in ["NarrativeText", "Text", "Table", "Image", "Title", "Header"]),
                "pages_processed": pages_to_process,
                "total_pages": total_pages,
                "processing_mode": processing_mode
            }

            status.atomic_elements = len(all_elements)
            status.partitioning = "completed"
            status.log("Partitioning step completed successfully")
            if update_status:
                update_status()

            return all_elements

        except Exception as e:
            status.partitioning = "error"
            status.error_message = str(e)
            status.log(f"ERROR in partitioning: {str(e)}")
            if update_status:
                update_status()
            raise

    def create_chunks(self, elements: List[Any], status: ProcessingStatus, update_status: callable = None) -> List[Any]:
        """Create semantic chunks from elements."""
        from unstructured.chunking.title import chunk_by_title

        status.chunking = "processing"
        status.current_step = "chunking"
        status.progress_message = "Creating semantic chunks from extracted elements..."
        status.log(f"Starting chunking of {len(elements)} elements")
        status.log("Chunking parameters: max_chars=3000, new_after=2400, combine_under=500")
        if update_status:
            update_status()

        try:
            chunks = chunk_by_title(
                elements,
                max_characters=3000,
                new_after_n_chars=2400,
                combine_text_under_n_chars=500
            )

            # Calculate stats
            total_chars = sum(len(chunk.text) for chunk in chunks)
            status.chunks_created = len(chunks)
            status.total_chunks = len(chunks)
            status.avg_chunk_size = total_chars // len(chunks) if chunks else 0

            status.log(f"Created {len(chunks)} chunks from {len(elements)} elements")
            status.log(f"Average chunk size: {status.avg_chunk_size} characters")

            status.chunking = "completed"
            status.log("Chunking step completed successfully")
            if update_status:
                update_status()

            return chunks

        except Exception as e:
            status.chunking = "error"
            status.error_message = str(e)
            status.log(f"ERROR in chunking: {str(e)}")
            raise

    def _separate_content_types(self, chunk) -> Dict[str, Any]:
        """Analyze content types in a chunk."""
        content_data = {
            'text': chunk.text,
            'tables': [],
            'images': [],
            'types': ['text']
        }

        if hasattr(chunk, 'metadata') and hasattr(chunk.metadata, 'orig_elements'):
            for element in chunk.metadata.orig_elements:
                element_type = type(element).__name__

                if element_type == 'Table':
                    content_data['types'].append('table')
                    table_html = getattr(element.metadata, 'text_as_html', element.text)
                    content_data['tables'].append(table_html)

                elif element_type == 'Image':
                    if hasattr(element, 'metadata') and hasattr(element.metadata, 'image_base64'):
                        content_data['types'].append('image')
                        content_data['images'].append(element.metadata.image_base64)

        content_data['types'] = list(set(content_data['types']))
        return content_data

    def _create_ai_summary(self, text: str, tables: List[str], images: List[str], chunk_num: int, status: ProcessingStatus) -> str:
        """Create AI-enhanced summary for mixed content."""
        try:
            llm = self._get_llm()

            status.log(f"  Chunk {chunk_num}: Sending to GPT-4o-mini for summarization...")
            if tables:
                status.log(f"    - Including {len(tables)} table(s)")
            if images:
                status.log(f"    - Including {len(images)} image(s)")

            prompt_text = f"""You are creating a searchable description for document content retrieval.

CONTENT TO ANALYZE:
TEXT CONTENT:
{text}

"""
            if tables:
                prompt_text += "TABLES:\n"
                for i, table in enumerate(tables):
                    prompt_text += f"Table {i+1}:\n{table}\n\n"

            prompt_text += """
YOUR TASK:
Generate a comprehensive, searchable description that covers:
1. Key facts, numbers, and data points from text and tables
2. Main topics and concepts discussed
3. Questions this content could answer
4. Visual content analysis (charts, diagrams, patterns in images)
5. Alternative search terms users might use

Make it detailed and searchable - prioritize findability over brevity.

SEARCHABLE DESCRIPTION:"""

            message_content = [{"type": "text", "text": prompt_text}]

            # Add images to message
            for idx, image_base64 in enumerate(images[:3]):  # Limit to 3 images
                status.log(f"    - Adding image {idx+1} to LLM request")
                message_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                })

            message = HumanMessage(content=message_content)
            response = llm.invoke([message])

            status.log(f"  Chunk {chunk_num}: AI summary generated ({len(response.content)} chars)")

            return response.content

        except Exception as e:
            status.log(f"  Chunk {chunk_num}: AI summary FAILED - {str(e)}")
            # Fallback to simple summary
            summary = f"{text[:500]}..."
            if tables:
                summary += f" [Contains {len(tables)} table(s)]"
            if images:
                summary += f" [Contains {len(images)} image(s)]"
            return summary

    MAX_CONCURRENT_LLM_CALLS = 8  # Concurrent OpenAI requests for summarization

    def _process_mixed_content_chunk(self, args: Tuple[int, str, List[str], List[str]]) -> Tuple[int, str]:
        """Process a single mixed-content chunk with AI. Returns (chunk_index, enhanced_content)."""
        chunk_idx, text, tables, images = args

        try:
            llm = self._get_llm()

            prompt_text = f"""You are creating a searchable description for document content retrieval.

CONTENT TO ANALYZE:
TEXT CONTENT:
{text}

"""
            if tables:
                prompt_text += "TABLES:\n"
                for i, table in enumerate(tables):
                    prompt_text += f"Table {i+1}:\n{table}\n\n"

            prompt_text += """
YOUR TASK:
Generate a comprehensive, searchable description that covers:
1. Key facts, numbers, and data points from text and tables
2. Main topics and concepts discussed
3. Questions this content could answer
4. Visual content analysis (charts, diagrams, patterns in images)
5. Alternative search terms users might use

Make it detailed and searchable - prioritize findability over brevity.

SEARCHABLE DESCRIPTION:"""

            message_content = [{"type": "text", "text": prompt_text}]

            # Add images to message (limit to 3)
            for image_base64 in images[:3]:
                message_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                })

            message = HumanMessage(content=message_content)
            response = llm.invoke([message])

            return (chunk_idx, response.content)

        except Exception as e:
            logger.error(f"Error processing chunk {chunk_idx}: {e}")
            # Fallback to simple summary
            summary = f"{text[:500]}..."
            if tables:
                summary += f" [Contains {len(tables)} table(s)]"
            if images:
                summary += f" [Contains {len(images)} image(s)]"
            return (chunk_idx, summary)

    def summarize_chunks(self, chunks: List[Any], status: ProcessingStatus, update_status: callable = None) -> List[ProcessedChunk]:
        """Process chunks with AI summarization using concurrent processing for mixed content."""
        status.summarization = "processing"
        status.current_step = "summarization"
        status.total_chunks = len(chunks)
        status.progress_message = f"Analyzing {len(chunks)} chunks..."
        status.log(f"Starting AI summarization for {len(chunks)} chunks")
        if update_status:
            update_status()

        try:
            # First pass: Separate text-only from mixed content chunks
            text_only_chunks = []  # (index, chunk, content_data)
            mixed_content_chunks = []  # (index, chunk, content_data)

            status.log("Phase 1: Analyzing chunk content types...")
            if update_status:
                update_status()

            for i, chunk in enumerate(chunks):
                content_data = self._separate_content_types(chunk)
                if content_data['tables'] or content_data['images']:
                    mixed_content_chunks.append((i, chunk, content_data))
                else:
                    text_only_chunks.append((i, chunk, content_data))

            status.log(f"  - Text-only chunks: {len(text_only_chunks)} (no API call needed)")
            status.log(f"  - Mixed content chunks: {len(mixed_content_chunks)} (will use GPT-4o-mini)")
            if update_status:
                update_status()

            # Initialize results array
            results = [None] * len(chunks)

            # Process text-only chunks immediately (no API call)
            status.log("Phase 2: Processing text-only chunks...")
            if update_status:
                update_status()

            for idx, chunk, content_data in text_only_chunks:
                page_number = 1
                if hasattr(chunk, 'metadata') and hasattr(chunk.metadata, 'page_number'):
                    page_number = chunk.metadata.page_number or 1

                results[idx] = ProcessedChunk(
                    chunk_id=str(uuid.uuid4()),
                    content=content_data['text'],
                    enhanced_content=content_data['text'],  # Use raw text
                    page_number=page_number,
                    char_count=len(content_data['text']),
                    content_types=content_data['types'],
                    tables_html=content_data['tables'],
                    images_base64=content_data['images'],
                    metadata={}
                )

            status.log(f"  Processed {len(text_only_chunks)} text-only chunks instantly")
            if update_status:
                update_status()

            # Process mixed content chunks concurrently
            if mixed_content_chunks:
                status.log(f"Phase 3: Processing {len(mixed_content_chunks)} mixed-content chunks with {self.MAX_CONCURRENT_LLM_CALLS} concurrent workers...")
                status.progress_message = f"Sending {len(mixed_content_chunks)} chunks to GPT-4o-mini concurrently..."
                if update_status:
                    update_status()

                # Prepare tasks for concurrent processing
                tasks = [
                    (idx, content_data['text'], content_data['tables'], content_data['images'])
                    for idx, chunk, content_data in mixed_content_chunks
                ]

                # Process concurrently
                completed = 0
                with ThreadPoolExecutor(max_workers=self.MAX_CONCURRENT_LLM_CALLS) as executor:
                    future_to_idx = {
                        executor.submit(self._process_mixed_content_chunk, task): task[0]
                        for task in tasks
                    }

                    for future in as_completed(future_to_idx):
                        original_idx = future_to_idx[future]
                        try:
                            chunk_idx, enhanced_content = future.result()

                            # Find the original chunk data
                            _, chunk, content_data = next(
                                (item for item in mixed_content_chunks if item[0] == chunk_idx),
                                (None, None, None)
                            )

                            if chunk is not None:
                                page_number = 1
                                if hasattr(chunk, 'metadata') and hasattr(chunk.metadata, 'page_number'):
                                    page_number = chunk.metadata.page_number or 1

                                results[chunk_idx] = ProcessedChunk(
                                    chunk_id=str(uuid.uuid4()),
                                    content=content_data['text'],
                                    enhanced_content=enhanced_content,
                                    page_number=page_number,
                                    char_count=len(content_data['text']),
                                    content_types=content_data['types'],
                                    tables_html=content_data['tables'],
                                    images_base64=content_data['images'],
                                    metadata={}
                                )

                            completed += 1
                            status.current_chunk = len(text_only_chunks) + completed
                            status.progress_message = f"AI summarization: {completed}/{len(mixed_content_chunks)} mixed chunks done"
                            status.log(f"  Chunk {chunk_idx + 1}: AI summary generated ({len(enhanced_content)} chars)")
                            if update_status:
                                update_status()

                        except Exception as e:
                            status.log(f"  Chunk {original_idx + 1}: ERROR - {str(e)}")
                            completed += 1
                            if update_status:
                                update_status()

            # Filter out any None results (shouldn't happen, but safety check)
            processed_chunks = [r for r in results if r is not None]

            status.summarization = "completed"
            status.log(f"Summarization complete. Processed {len(processed_chunks)} chunks")
            status.log(f"  - {len(text_only_chunks)} text-only (instant)")
            status.log(f"  - {len(mixed_content_chunks)} mixed-content (AI-enhanced)")
            if update_status:
                update_status()

            return processed_chunks

        except Exception as e:
            status.summarization = "error"
            status.error_message = str(e)
            status.log(f"ERROR in summarization: {str(e)}")
            if update_status:
                update_status()
            raise

    def vectorize_and_store(
        self,
        chunks: List[ProcessedChunk],
        document_name: str,
        tenant_id: str,
        department: str,
        access_level: str,
        status: ProcessingStatus,
        update_status: callable = None,
        arxiv_id: str = None,
        visibility: str = "public",
        uploaded_by_user_id: str = "anonymous",
        file_path: str = None
    ) -> int:
        """Generate embeddings and store in Qdrant."""
        status.vectorization = "processing"
        status.current_step = "vectorization"
        status.total_chunks = len(chunks)
        status.progress_message = f"Generating embeddings for {len(chunks)} chunks..."
        status.log(f"Starting vectorization for {len(chunks)} chunks")
        status.log(f"Metadata: tenant={tenant_id}, dept={department}, access={access_level}")
        status.log(f"Visibility: {visibility}, User: {uploaded_by_user_id}")
        if arxiv_id:
            status.log(f"arXiv ID: {arxiv_id}")
        if file_path:
            status.log(f"Stored file path: {file_path}")
        if update_status:
            update_status()

        try:
            self.ensure_collection_exists(status)
            if update_status:
                update_status()

            client = self._get_qdrant_client()
            embeddings = self._get_embeddings()

            # Generate embeddings for all chunks
            status.log("Generating embeddings using text-embedding-3-small...")
            texts = [chunk.enhanced_content for chunk in chunks]

            status.log(f"Sending {len(texts)} texts to OpenAI Embeddings API...")
            if update_status:
                update_status()
            vectors = embeddings.embed_documents(texts)
            status.log(f"Received {len(vectors)} embedding vectors (dim={len(vectors[0]) if vectors else 0})")
            if update_status:
                update_status()

            # Prepare points for Qdrant
            status.log("Preparing points for Qdrant upsert...")
            points = []
            for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
                status.current_chunk = i + 1
                payload = {
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "enhanced_content": chunk.enhanced_content,
                    "document_name": document_name,
                    "title": document_name,  # For RAG tool compatibility
                    "page_number": chunk.page_number,
                    "char_count": chunk.char_count,
                    "content_types": chunk.content_types,
                    "tables_html": chunk.tables_html,
                    "images_base64": chunk.images_base64[:1] if chunk.images_base64 else [],
                    "tenant_id": tenant_id,
                    "department": department,
                    "access_level": access_level,
                    "visibility": visibility,
                    "uploaded_by_user_id": uploaded_by_user_id,
                }
                if arxiv_id:
                    payload["arxiv_id"] = arxiv_id
                if file_path:
                    payload["file_path"] = file_path
                point = PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload=payload
                )
                points.append(point)

            # Upsert to Qdrant
            status.log(f"Upserting {len(points)} points to Qdrant collection '{self.COLLECTION_NAME}'...")
            if update_status:
                update_status()
            client.upsert(
                collection_name=self.COLLECTION_NAME,
                points=points
            )

            status.vectorization = "completed"
            status.log(f"Successfully stored {len(points)} vectors in Qdrant!")
            status.log(f"Document '{document_name}' processing complete")
            if update_status:
                update_status()

            return len(points)

        except Exception as e:
            status.vectorization = "error"
            status.error_message = str(e)
            status.log(f"ERROR in vectorization: {str(e)}")
            if update_status:
                update_status()
            raise

    def process_document(
        self,
        file_path: str,
        document_name: str,
        tenant_id: str,
        department: str,
        access_level: str = "public",
        processing_mode: str = "hi_res",
        status_callback: callable = None,
        arxiv_id: str = None,
        visibility: str = "public",
        user_id: str = "anonymous",
        store_pdf: bool = True
    ) -> tuple[ProcessingStatus, List[ProcessedChunk]]:
        """Run the complete document processing pipeline.

        Args:
            file_path: Path to the document file
            document_name: Name of the document
            tenant_id: Tenant identifier
            department: Department name
            access_level: Access level (public, internal, confidential)
            processing_mode: 'fast', 'balanced', or 'hi_res' (default)
            status_callback: Optional callback function to call with status updates
            arxiv_id: Optional arXiv ID for the paper
            visibility: 'public' or 'private' (default: 'public')
            user_id: User ID who uploaded the document (default: 'anonymous')
            store_pdf: Whether to store the PDF locally (default: True)
        """
        status = ProcessingStatus()

        def update_status():
            """Call callback with current status."""
            if status_callback:
                status_callback(status)

        status.log("=" * 50)
        status.log(f"STARTING DOCUMENT PROCESSING PIPELINE")
        status.log(f"Document: {document_name}")
        status.log(f"File: {file_path}")
        status.log(f"Processing Mode: {processing_mode.upper()}")
        status.log(f"Visibility: {visibility}, User: {user_id}")
        status.log("=" * 50)
        update_status()

        # Step 0: Store PDF locally
        stored_file_path = None
        if store_pdf:
            try:
                status.log("--- STEP 0: STORING PDF ---")
                stored_file_path = self._store_pdf(
                    source_path=file_path,
                    document_name=document_name,
                    tenant_id=tenant_id,
                    department=department,
                    user_id=user_id
                )
                status.log(f"PDF stored at: {stored_file_path}")
                update_status()
            except Exception as e:
                status.log(f"WARNING: Failed to store PDF: {e}")
                # Continue processing even if storage fails

        # Step 1: Upload (already done)
        status.upload = "completed"
        status.queued = "completed"
        status.log("Upload and queue steps completed")
        update_status()

        # Step 2: Partition
        status.log("")
        status.log("--- STEP 1: PARTITIONING ---")
        update_status()
        elements = self.partition_document(file_path, status, update_status, processing_mode)

        # Step 3: Chunk
        status.log("")
        status.log("--- STEP 2: CHUNKING ---")
        update_status()
        chunks = self.create_chunks(elements, status, update_status)

        # Step 4: Summarize
        status.log("")
        status.log("--- STEP 3: SUMMARIZATION ---")
        update_status()
        processed_chunks = self.summarize_chunks(chunks, status, update_status)

        # Step 5: Vectorize and Store
        status.log("")
        status.log("--- STEP 4: VECTORIZATION & STORAGE ---")
        update_status()
        self.vectorize_and_store(
            processed_chunks,
            document_name,
            tenant_id,
            department,
            access_level,
            status,
            update_status,
            arxiv_id=arxiv_id,
            visibility=visibility,
            uploaded_by_user_id=user_id,
            file_path=stored_file_path
        )

        status.log("")
        status.log("=" * 50)
        status.log("PIPELINE COMPLETED SUCCESSFULLY!")
        status.log("=" * 50)
        update_status()

        return status, processed_chunks

    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the Qdrant collection."""
        try:
            client = self._get_qdrant_client()

            # Check if collection exists
            collections = client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.COLLECTION_NAME not in collection_names:
                return {
                    "collection_name": self.COLLECTION_NAME,
                    "vectors_count": 0,
                    "points_count": 0,
                    "status": "not_created",
                }

            collection_info = client.get_collection(self.COLLECTION_NAME)

            return {
                "collection_name": self.COLLECTION_NAME,
                "vectors_count": collection_info.vectors_count or 0,
                "points_count": collection_info.points_count or 0,
                "status": collection_info.status.value if collection_info.status else "unknown",
            }
        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            return {
                "collection_name": self.COLLECTION_NAME,
                "vectors_count": 0,
                "points_count": 0,
                "error": str(e)
            }
