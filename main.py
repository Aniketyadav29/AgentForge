"""
AgentForge — FastAPI Application Server
Multi-Agent AI Research Assistant with real-time SSE streaming.

Endpoints:
  POST /api/research             — Submit a research query
  GET  /api/research/{id}/stream — SSE stream of agent activity
  GET  /api/research/{id}/result — Get final research report
  GET  /api/history              — List past research sessions
  GET  /api/history/{id}         — Get a specific past report
  GET  /health                   — Health check
  GET  /                         — Serve dashboard
"""

import os
import sys
import uuid
import json
import glob
import asyncio
import threading
import time
from datetime import datetime
from contextlib import asynccontextmanager

# Force UTF-8 stdout encoding on Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from sse_starlette.sse import EventSourceResponse

from models.schemas import ResearchRequest, ResearchResponse, HealthResponse
from models.schemas import (
    DocumentUploadResponse, DocumentQueryRequest,
    DocumentQueryResponse, SourceChunk,
)
from database.db import (
    init_db,
    save_session,
    update_session,
    get_session_by_id,
    get_all_sessions,
    delete_session,
    save_document_session,
    get_document_session,
    get_all_document_sessions,
    delete_document_session,
)
from agents.crew import create_session, get_session as get_crew_session, list_sessions

# Load environment variables
load_dotenv()

# Verify API keys
if not os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY") == "your_groq_api_key_here":
    print("\n[!] WARNING: GROQ_API_KEY not set in .env file!")
    print("   Get your key at: https://console.groq.com\n")

if not os.environ.get("SERPER_API_KEY") or os.environ.get("SERPER_API_KEY") == "your_serper_api_key_here":
    print("\n[!] WARNING: SERPER_API_KEY not set in .env file!")
    print("   Get your key at: https://serper.dev/\n")


VERSION = "1.0.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

# Ensure static and upload directories exist
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "js"), exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    init_db()
    print("\n[+] AgentForge - Multi-Agent AI Research Assistant")
    print(f"    Version: {VERSION}")
    print(f"    Dashboard: http://127.0.0.1:8000")
    print(f"    API Docs:  http://127.0.0.1:8000/docs\n")
    yield
    print("\n[-] AgentForge shutting down...\n")


app = FastAPI(
    title="AgentForge — Multi-Agent AI Research Assistant",
    description="An industry-grade multi-agent system where specialized AI agents "
                "collaborate to research topics, scrape web data, analyze information, "
                "and generate comprehensive reports.",
    version=VERSION,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ============================================================
# Middleware
# ============================================================

@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    """Add request timing to response headers."""
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    response.headers["X-Process-Time"] = f"{duration:.2f}ms"
    return response


# ============================================================
# Page Routes
# ============================================================

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard():
    """Serve the main dashboard page."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse(
            content="<h1>AgentForge</h1><p>Dashboard not found. Run the build process.</p>",
            status_code=200,
        )
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ============================================================
# API Routes
# ============================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=VERSION,
        timestamp=datetime.now().isoformat(),
        active_sessions=len(list_sessions()),
    )


@app.post("/api/research", response_model=ResearchResponse)
async def start_research(request: ResearchRequest):
    """
    Submit a new research query.
    Returns a task_id that can be used to stream updates and get results.
    """
    # Validate depth
    if request.depth not in ("quick", "detailed", "deep"):
        raise HTTPException(status_code=400, detail="Depth must be 'quick', 'detailed', or 'deep'")

    # Generate task ID
    task_id = str(uuid.uuid4())[:12]

    # Append focus areas to topic if provided
    topic = request.topic
    if request.focus_areas:
        topic += f" (Focus areas: {', '.join(request.focus_areas)})"

    # Save to database
    save_session(task_id, topic, request.depth, status="running")

    # Create crew session
    crew = create_session(task_id)

    # Run in background thread (CrewAI is synchronous)
    def _run():
        try:
            result = crew.run(topic=topic, depth=request.depth)
            # Persist result
            update_session(
                task_id=task_id,
                status="completed",
                report=result.get("report", ""),
                duration_seconds=result.get("duration_seconds"),
                agents_used=result.get("agents_used"),
                activity_log=crew.activity_log.get_all(),
            )
        except Exception as e:
            update_session(
                task_id=task_id,
                status="failed",
                error_message=str(e),
                activity_log=crew.activity_log.get_all(),
            )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return ResearchResponse(
        task_id=task_id,
        status="running",
        topic=topic,
        depth=request.depth,
        message="Research started. Use the stream endpoint to follow agent activity.",
        timestamp=datetime.now().isoformat(),
    )


@app.get("/api/research/{task_id}/stream")
async def stream_agent_activity(task_id: str):
    """
    SSE endpoint for real-time agent activity streaming.
    Sends new agent activities as they happen.
    """
    crew = get_crew_session(task_id)
    if not crew:
        raise HTTPException(status_code=404, detail=f"Research session '{task_id}' not found")

    async def event_generator():
        """Generate SSE events from the agent activity log."""
        while True:
            # Check for new activities
            new_activities = crew.activity_log.get_new()
            for activity in new_activities:
                yield {
                    "event": "agent_activity",
                    "data": json.dumps(activity),
                }

            # Check if crew is done
            if crew.status in ("completed", "failed"):
                # Send final status event
                yield {
                    "event": "research_complete",
                    "data": json.dumps({
                        "status": crew.status,
                        "task_id": task_id,
                        "error": crew.error,
                    }),
                }
                break

            # Small delay to avoid busy-waiting
            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@app.get("/api/research/{task_id}/result")
async def get_research_result(task_id: str):
    """Get the final research report for a completed session."""
    # Try in-memory first
    crew = get_crew_session(task_id)
    if crew and crew.result:
        return {
            "task_id": task_id,
            "status": crew.status,
            **crew.result,
            "activities": crew.activity_log.get_all(),
        }

    # Fall back to database
    session = get_session_by_id(task_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Research session '{task_id}' not found")

    result = dict(session)
    # Parse JSON fields
    if result.get("agents_used") and isinstance(result["agents_used"], str):
        try:
            result["agents_used"] = json.loads(result["agents_used"])
        except Exception:
            result["agents_used"] = []
    if result.get("activity_log") and isinstance(result["activity_log"], str):
        try:
            result["activity_log"] = json.loads(result["activity_log"])
        except Exception:
            result["activity_log"] = []

    return result


@app.get("/api/history")
async def get_research_history(limit: int = 50, offset: int = 0):
    """Get list of all past research sessions."""
    sessions = get_all_sessions(limit=limit, offset=offset)
    for s in sessions:
        if s.get("agents_used") and isinstance(s["agents_used"], str):
            try:
                s["agents_used"] = json.loads(s["agents_used"])
            except Exception:
                s["agents_used"] = []
    return {
        "sessions": sessions,
        "total": len(sessions),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/history/{task_id}")
async def get_history_item(task_id: str):
    """Get a specific past research report."""
    session = get_session_by_id(task_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{task_id}' not found")

    result = dict(session)
    if result.get("agents_used") and isinstance(result["agents_used"], str):
        try:
            result["agents_used"] = json.loads(result["agents_used"])
        except Exception:
            result["agents_used"] = []
    if result.get("activity_log") and isinstance(result["activity_log"], str):
        try:
            result["activity_log"] = json.loads(result["activity_log"])
        except Exception:
            result["activity_log"] = []

    return result


@app.delete("/api/history/{task_id}")
async def delete_history_item(task_id: str):
    """Delete a research session from history."""
    deleted = delete_session(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session '{task_id}' not found")
    return {"status": "deleted", "task_id": task_id}


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a document session and uploaded files."""
    deleted = delete_document_session(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")

    for f in glob.glob(os.path.join(UPLOAD_DIR, f"{doc_id}_*")):
        try:
            os.remove(f)
        except Exception:
            pass

    return {"status": "deleted", "doc_id": doc_id}


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
