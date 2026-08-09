"""
AgentForge — Pydantic Data Models
Request/response schemas for the FastAPI endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime


class ResearchRequest(BaseModel):
    """Request to start a new research session."""
    topic: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="The research topic or question to investigate",
    )
    depth: str = Field(
        default="detailed",
        description="Research depth: 'quick' (3 aspects), 'detailed' (5-7), or 'deep' (8-10)",
    )
    focus_areas: Optional[List[str]] = Field(
        default=None,
        description="Optional specific areas to focus the research on",
    )


class ResearchResponse(BaseModel):
    """Response after submitting a research request."""
    task_id: str
    status: str
    topic: str
    depth: str
    message: str
    timestamp: str
    # Populated only on Vercel (synchronous run) so the frontend can
    # cache the full result without a second DB round-trip.
    report: Optional[str] = None
    activity_log: Optional[List[Any]] = None
    agents_used: Optional[List[str]] = None
    duration_seconds: Optional[float] = None
    activity_count: Optional[int] = None


class AgentActivity(BaseModel):
    """A single agent activity event for real-time streaming."""
    id: str
    agent: str
    action: str
    content: str
    timestamp: str


class ResearchReport(BaseModel):
    """Complete research report result."""
    task_id: str
    topic: str
    depth: str
    report: str
    duration_seconds: float
    agents_used: List[str]
    activity_count: int
    timestamp: str
    status: str


class HistoryItem(BaseModel):
    """A research session in the history."""
    id: int
    task_id: str
    topic: str
    depth: str
    status: str
    report: Optional[str] = None
    duration_seconds: Optional[float] = None
    agents_used: Optional[str] = None
    activity_log: Optional[str] = None
    created_at: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    timestamp: str
    active_sessions: int


# ─────────────────────────────────────────────────────────────────────────────
# Document Analyzer Schemas
# ─────────────────────────────────────────────────────────────────────────────

class DocumentUploadResponse(BaseModel):
    """Response after a file is uploaded and processed."""
    doc_id: str
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    has_tables: bool
    message: str
    timestamp: str


class ResearchPdfExportRequest(BaseModel):
    """Research content provided by the browser for PDF export."""
    title: str = Field(default="AgentForge Research Report", min_length=1, max_length=500)
    report: str = Field(..., min_length=1, max_length=200000)


class DocumentQueryRequest(BaseModel):
    """Request to ask a question about an uploaded document."""
    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="The question to answer based on the document",
    )


class SourceChunk(BaseModel):
    """A retrieved context chunk used to ground an answer."""
    chunk: str
    score: float


class DocumentQueryResponse(BaseModel):
    """Answer to a document question with sources."""
    doc_id: str
    question: str
    answer: str
    sources: List[SourceChunk]
    computation_steps: Optional[str] = None
    timestamp: str


class DocumentListItem(BaseModel):
    """Summary of an uploaded document in the list view."""
    doc_id: str
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    has_tables: bool
    created_at: str
