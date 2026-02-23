"""Progress tracker for real-time updates during content generation."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import threading

# Context variables to store current session info for tools to access
current_thread_id: ContextVar[Optional[str]] = ContextVar('current_thread_id', default=None)
current_user_id: ContextVar[Optional[str]] = ContextVar('current_user_id', default=None)
current_tenant_id: ContextVar[Optional[str]] = ContextVar('current_tenant_id', default=None)
current_department: ContextVar[Optional[str]] = ContextVar('current_department', default=None)


def set_current_thread_id(thread_id: str) -> None:
    """Set the current thread ID for tool context."""
    current_thread_id.set(thread_id)


def get_current_thread_id() -> Optional[str]:
    """Get the current thread ID from context."""
    return current_thread_id.get()


def set_current_user_id(user_id: str) -> None:
    """Set the current user ID for tool context."""
    current_user_id.set(user_id)


def get_current_user_id() -> Optional[str]:
    """Get the current user ID from context."""
    return current_user_id.get()


def set_current_tenant_id(tenant_id: str) -> None:
    """Set the current tenant ID for tool context."""
    current_tenant_id.set(tenant_id)


def get_current_tenant_id() -> Optional[str]:
    """Get the current tenant ID from context."""
    return current_tenant_id.get()


def set_current_department(department: str) -> None:
    """Set the current department for tool context."""
    current_department.set(department)


def get_current_department() -> Optional[str]:
    """Get the current department from context."""
    return current_department.get()


def set_session_context(
    thread_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    department: Optional[str] = None,
) -> None:
    """Set all session context variables at once."""
    if thread_id:
        current_thread_id.set(thread_id)
    if user_id:
        current_user_id.set(user_id)
    if tenant_id:
        current_tenant_id.set(tenant_id)
    if department:
        current_department.set(department)

@dataclass
class GenerationProgress:
    """Progress state for a content generation task."""
    tool_name: str
    current_step: str
    step_number: int
    total_steps: int
    iteration: int = 1
    max_iterations: int = 3
    draft: Optional[str] = None
    quality_score: Optional[float] = None
    message: str = ""
    completed: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EmbeddingProgress:
    """Progress state for document embedding."""
    document_name: str
    arxiv_id: Optional[str] = None

    # Step statuses: pending, processing, completed, error
    download_status: str = "pending"
    partition_status: str = "pending"
    chunking_status: str = "pending"
    summarization_status: str = "pending"
    vectorization_status: str = "pending"

    # Progress details
    current_step: str = "starting"
    message: str = ""

    # Partition progress
    total_pages: int = 0
    current_page: int = 0
    elements_extracted: int = 0

    # Chunk progress
    total_chunks: int = 0
    current_chunk: int = 0

    # Logs (last N entries)
    logs: list = field(default_factory=list)

    # Final stats
    completed: bool = False
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def add_log(self, message: str):
        """Add a timestamped log entry."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")
        # Keep only last 20 logs
        if len(self.logs) > 20:
            self.logs = self.logs[-20:]
        self.timestamp = datetime.now()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "document_name": self.document_name,
            "arxiv_id": self.arxiv_id,
            "steps": {
                "download": self.download_status,
                "partition": self.partition_status,
                "chunking": self.chunking_status,
                "summarization": self.summarization_status,
                "vectorization": self.vectorization_status,
            },
            "current_step": self.current_step,
            "message": self.message,
            "partition_progress": {
                "current": self.current_page,
                "total": self.total_pages,
            },
            "chunk_progress": {
                "current": self.current_chunk,
                "total": self.total_chunks,
            },
            "elements_extracted": self.elements_extracted,
            "logs": self.logs,
            "completed": self.completed,
            "error": self.error,
        }


class ProgressTracker:
    """Thread-safe progress tracker for content generation and embedding."""

    def __init__(self):
        self._progress: dict[str, GenerationProgress] = {}
        self._embedding_progress: dict[str, EmbeddingProgress] = {}
        self._lock = threading.Lock()

    def start(self, thread_id: str, tool_name: str) -> None:
        """Start tracking progress for a thread."""
        with self._lock:
            self._progress[thread_id] = GenerationProgress(
                tool_name=tool_name,
                current_step="Starting",
                step_number=0,
                total_steps=4,  # generate, evaluate, (regenerate, evaluate) x max_iter
                message=f"Starting {tool_name.replace('_', ' ')}..."
            )

    def update(
        self,
        thread_id: str,
        step: str,
        step_number: int,
        message: str,
        iteration: int = 1,
        draft: Optional[str] = None,
        quality_score: Optional[float] = None,
    ) -> None:
        """Update progress for a thread."""
        with self._lock:
            if thread_id in self._progress:
                prog = self._progress[thread_id]
                prog.current_step = step
                prog.step_number = step_number
                prog.message = message
                prog.iteration = iteration
                prog.timestamp = datetime.utcnow()
                if draft:
                    prog.draft = draft
                if quality_score is not None:
                    prog.quality_score = quality_score

    def complete(self, thread_id: str, final_content: str, quality_score: float) -> None:
        """Mark generation as complete."""
        with self._lock:
            if thread_id in self._progress:
                prog = self._progress[thread_id]
                prog.completed = True
                prog.draft = final_content
                prog.quality_score = quality_score
                prog.current_step = "Complete"
                prog.message = f"Generation complete (Score: {quality_score:.1f}/10)"

    def get(self, thread_id: str) -> Optional[GenerationProgress]:
        """Get current progress for a thread."""
        with self._lock:
            return self._progress.get(thread_id)

    def clear(self, thread_id: str) -> None:
        """Clear progress for a thread."""
        with self._lock:
            self._progress.pop(thread_id, None)

    def get_and_clear_if_complete(self, thread_id: str) -> Optional[GenerationProgress]:
        """Get progress and clear if complete."""
        with self._lock:
            prog = self._progress.get(thread_id)
            if prog and prog.completed:
                self._progress.pop(thread_id, None)
            return prog

    # =========================================================================
    # EMBEDDING PROGRESS METHODS
    # =========================================================================

    def start_embedding(
        self,
        thread_id: str,
        document_name: str,
        arxiv_id: Optional[str] = None
    ) -> None:
        """Start tracking embedding progress for a thread."""
        with self._lock:
            self._embedding_progress[thread_id] = EmbeddingProgress(
                document_name=document_name,
                arxiv_id=arxiv_id,
            )
            self._embedding_progress[thread_id].add_log(f"Starting embedding: {document_name}")

    def update_embedding(
        self,
        thread_id: str,
        step: Optional[str] = None,
        status: Optional[str] = None,
        message: Optional[str] = None,
        current_page: Optional[int] = None,
        total_pages: Optional[int] = None,
        current_chunk: Optional[int] = None,
        total_chunks: Optional[int] = None,
        elements_extracted: Optional[int] = None,
        log_message: Optional[str] = None,
    ) -> None:
        """Update embedding progress."""
        with self._lock:
            if thread_id not in self._embedding_progress:
                return

            prog = self._embedding_progress[thread_id]

            if step:
                prog.current_step = step
            if message:
                prog.message = message

            # Update step status
            if step and status:
                if step == "download":
                    prog.download_status = status
                elif step == "partition":
                    prog.partition_status = status
                elif step == "chunking":
                    prog.chunking_status = status
                elif step == "summarization":
                    prog.summarization_status = status
                elif step == "vectorization":
                    prog.vectorization_status = status

            # Update progress numbers
            if current_page is not None:
                prog.current_page = current_page
            if total_pages is not None:
                prog.total_pages = total_pages
            if current_chunk is not None:
                prog.current_chunk = current_chunk
            if total_chunks is not None:
                prog.total_chunks = total_chunks
            if elements_extracted is not None:
                prog.elements_extracted = elements_extracted

            # Add log
            if log_message:
                prog.add_log(log_message)

            prog.timestamp = datetime.now()

    def complete_embedding(self, thread_id: str, success: bool = True, error: Optional[str] = None) -> None:
        """Mark embedding as complete."""
        with self._lock:
            if thread_id in self._embedding_progress:
                prog = self._embedding_progress[thread_id]
                prog.completed = True
                if error:
                    prog.error = error
                    prog.add_log(f"ERROR: {error}")
                else:
                    prog.add_log("Embedding completed successfully!")

    def get_embedding_progress(self, thread_id: str) -> Optional[EmbeddingProgress]:
        """Get embedding progress for a thread."""
        with self._lock:
            return self._embedding_progress.get(thread_id)

    def clear_embedding(self, thread_id: str) -> None:
        """Clear embedding progress for a thread."""
        with self._lock:
            self._embedding_progress.pop(thread_id, None)


# Global singleton instance
_tracker: Optional[ProgressTracker] = None


def get_progress_tracker() -> ProgressTracker:
    """Get the global progress tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = ProgressTracker()
    return _tracker
