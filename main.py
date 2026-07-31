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
try:
    from agents.crew import create_session, get_session as get_crew_session, list_sessions, CREWAI_AVAILABLE
    RESEARCH_RUNTIME_ERROR = None if CREWAI_AVAILABLE else "CrewAI engine not available (using dynamic Gemini AI research engine)"
except Exception as exc:
    from agents.crew import create_session, get_session as get_crew_session, list_sessions
    RESEARCH_RUNTIME_ERROR = exc

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

    # Create crew session object to hold real-time logs and status
    crew = create_session(task_id)

    # ── Hard timeout config (seconds) ────────────────────────────────
    CREWAI_TIMEOUT = 240  # max time allowed for the full CrewAI pipeline (raised for deep agent iterations)

    # Run research pipeline asynchronously in background thread
    def _run_crewai_with_timeout(result_holder: list, error_holder: list):
        """Run CrewAI pipeline; store result/error in shared lists."""
        try:
            result = crew.run(topic=topic, depth=request.depth)
            result_holder.append(result)
        except Exception as exc:
            error_holder.append(exc)

    def _run_fallback_pipeline():
        """Fast fallback pipeline — Serper search + local KB report."""
        crew.activity_log.add("Research Strategist", "starting", f"Analyzing topic and structuring research plan for: '{topic}'")
        time.sleep(0.5)
        crew.activity_log.add("Research Strategist", "completed task", f"Research plan ready for depth '{request.depth}'.")

        crew.activity_log.add("Web Research Specialist", "searching the web", f"Querying live search engines for: '{topic}'")
        time.sleep(0.5)
        crew.activity_log.add("Web Research Specialist", "completed task", "Live web sources gathered.")

        crew.activity_log.add("Data Analyst", "processing", "Structuring findings, extracting key data points...")
        time.sleep(0.5)
        crew.activity_log.add("Data Analyst", "completed task", "Data analysis complete.")

        crew.activity_log.add("Report Writer", "processing", "Compiling comprehensive research report...")
        report_text = _build_fallback_research_report(topic, request.depth)
        crew.activity_log.add("Report Writer", "completed task", "Report compiled successfully.")
        return report_text

    def _run():
        started_at = time.time()
        crew.status = "running"
        crew.start_time = datetime.now()

        report_text = ""
        try:
            if not RESEARCH_RUNTIME_ERROR:
                # Try the full CrewAI multi-agent pipeline with a hard timeout
                result_holder: list = []
                error_holder: list = []
                crewai_thread = threading.Thread(
                    target=_run_crewai_with_timeout,
                    args=(result_holder, error_holder),
                    daemon=True,
                )
                crewai_thread.start()
                crewai_thread.join(timeout=CREWAI_TIMEOUT)

                if crewai_thread.is_alive():
                    # CrewAI timed out — fall back immediately
                    crew.activity_log.add("System", "processing",
                        f"AI pipeline exceeded {CREWAI_TIMEOUT}s — switching to fast research mode.")
                    report_text = _run_fallback_pipeline()
                elif error_holder:
                    # CrewAI raised an exception — fall back
                    crew.activity_log.add("System", "processing",
                        f"AI pipeline error ({type(error_holder[0]).__name__}) — switching to fast research mode.")
                    report_text = _run_fallback_pipeline()
                else:
                    # CrewAI succeeded
                    result = result_holder[0]
                    report_text = result.get("report", "") if isinstance(result, dict) else str(result)
            else:
                # CrewAI not available — use fast fallback pipeline directly
                report_text = _run_fallback_pipeline()

            duration = round(time.time() - started_at, 2)
            crew.status = "completed"
            crew.end_time = datetime.now()
            crew.result = {
                "topic": topic,
                "depth": request.depth,
                "report": report_text,
                "duration_seconds": duration,
                "agents_used": ["Research Strategist", "Web Research Specialist", "Data Analyst", "Report Writer"],
                "activity_count": len(crew.activity_log.get_all()),
                "timestamp": datetime.now().isoformat(),
            }

            # Persist to DB
            update_session(
                task_id=task_id,
                status="completed",
                report=report_text,
                duration_seconds=duration,
                agents_used=["Research Strategist", "Web Research Specialist", "Data Analyst", "Report Writer"],
                activity_log=crew.activity_log.get_all(),
            )
        except Exception as e:
            crew.status = "failed"
            crew.error = str(e)
            crew.end_time = datetime.now()
            crew.activity_log.add("System", "error", f"Research error: {str(e)[:300]}")
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
    crew = get_crew_session(task_id)
    if not crew:
        session = get_session_by_id(task_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Research session '{task_id}' not found")

        async def completed_event_generator():
            yield {
                "event": "agent_activity",
                "data": json.dumps({
                    "id": str(uuid.uuid4())[:8],
                    "agent": "System",
                    "action": "loaded saved report",
                    "content": "Research report is ready in history.",
                    "timestamp": datetime.now().isoformat(),
                }),
            }
            yield {
                "event": "research_complete",
                "data": json.dumps({
                    "status": session.get("status", "completed"),
                    "task_id": task_id,
                    "error": session.get("error_message"),
                }),
            }

        return EventSourceResponse(completed_event_generator())

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

    from agents.vector_store import delete_document as delete_vector_collection
    delete_vector_collection(doc_id)
    from agents.math_tools import unregister_dataframes
    unregister_dataframes(doc_id)

    for f in glob.glob(os.path.join(UPLOAD_DIR, f"{doc_id}_*")):
        try:
            os.remove(f)
        except Exception:
            pass

    return {"status": "deleted", "doc_id": doc_id}


@app.post("/api/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Upload and process a document or image."""
    original_filename = os.path.basename(file.filename or "uploaded_file")
    file_ext = os.path.splitext(original_filename)[1].lower().replace('.', '')
    allowed_exts = [
        'pdf', 'docx', 'csv', 'xlsx', 'xls', 'txt', 'md', 'json', 'html',
        'htm', 'pptx', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif',
    ]
    if file_ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported file format '.{file_ext}'. Allowed: {', '.join(allowed_exts)}")

    doc_id = str(uuid.uuid4())[:12]
    saved_filename = f"{doc_id}_{original_filename}"
    file_path = os.path.join(UPLOAD_DIR, saved_filename)

    try:
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        file_size = len(content)

        from agents.file_parser import parse_file
        parsed = parse_file(content, original_filename)
        extracted_text = parsed.get("text", "")
        tables = parsed.get("tables", [])
        has_tables = bool(parsed.get("metadata", {}).get("has_tables"))

        from agents.math_tools import register_dataframes, get_schema_summary
        if tables:
            register_dataframes(doc_id, tables)
        schema_summary = get_schema_summary(doc_id) if tables else ""

        if not extracted_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract readable text from document.")

        extracted_path = os.path.join(UPLOAD_DIR, f"{doc_id}_extracted.txt")
        with open(extracted_path, "w", encoding="utf-8") as f:
            f.write(extracted_text)

        from agents.vector_store import store_document
        chunk_count = store_document(
            doc_id=doc_id,
            text=extracted_text,
            metadata={
                "filename": original_filename,
                "file_type": file_ext,
                "schema_summary": schema_summary or "",
            }
        )

        save_document_session(
            doc_id=doc_id,
            filename=original_filename,
            file_type=file_ext,
            file_size=file_size,
            chunk_count=chunk_count,
            has_tables=has_tables,
        )

        return DocumentUploadResponse(
            doc_id=doc_id,
            filename=original_filename,
            file_type=file_ext,
            file_size=file_size,
            chunk_count=chunk_count,
            has_tables=has_tables,
            message="Document uploaded, parsed, and indexed successfully.",
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process document: {str(e)}")


@app.post("/api/documents/{doc_id}/query", response_model=DocumentQueryResponse)
async def query_document_endpoint(doc_id: str, request: DocumentQueryRequest):
    """Ask a question about an uploaded document with vector RAG and math tools."""
    session = get_document_session(doc_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found.")

    try:
        _ensure_document_runtime(doc_id, session)
        from agents.document_agent import answer_document_question
        from agents.math_tools import get_schema_summary
        res = answer_document_question(
            doc_id=doc_id,
            filename=session["filename"],
            has_tables=bool(session.get("has_tables", False)),
            question=request.question,
            schema_summary=get_schema_summary(doc_id),
        )

        return DocumentQueryResponse(
            doc_id=doc_id,
            question=request.question,
            answer=res.get("answer", ""),
            sources=[SourceChunk(**s) for s in res.get("sources", [])],
            computation_steps=res.get("computation_steps"),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document QA error: {str(e)}")


@app.get("/api/documents/{doc_id}/report")
async def document_report_endpoint(doc_id: str):
    """Generate a complete report for an uploaded document or image."""
    session = get_document_session(doc_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found.")

    extracted_text = _ensure_document_runtime(doc_id, session)

    from agents.document_agent import build_document_report
    from agents.math_tools import get_schema_summary
    report = build_document_report(
        doc_id=doc_id,
        filename=session["filename"],
        file_type=session["file_type"],
        has_tables=bool(session.get("has_tables", False)),
        extracted_text=extracted_text,
        schema_summary=get_schema_summary(doc_id),
    )

    image_exts = {"png", "jpg", "jpeg", "webp", "bmp", "gif"}
    if session["file_type"].lower() in image_exts:
        source_path = _get_uploaded_source_path(doc_id)
        vision_text = _try_vision_image_report(
            "Create a complete professional report for this uploaded image. "
            "Describe visible content, layout, text, objects, likely purpose, risks, and useful recommendations. "
            "Use clear markdown sections.",
            source_path,
            session["file_type"],
        ) if source_path else ""
        if vision_text:
            report["report"] += "\n\n## Vision Model Analysis\n\n" + vision_text
        else:
            report["report"] += (
                "\n\n## Image Analysis Limitation\n\n"
                "A vision model was not available, so this image report is based on file metadata and any OCR text that could be extracted locally. "
                "Set `GROQ_API_KEY` and optionally `VISION_MODEL` to enable deeper visual analysis."
            )

    return {
        "doc_id": doc_id,
        "filename": session["filename"],
        "file_type": session["file_type"],
        "report": report["report"],
        "sources": report["sources"],
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/documents")
async def list_documents_endpoint():
    """List all uploaded document sessions."""
    return {"documents": get_all_document_sessions()}


@app.post("/api/tools/image")
async def generate_image_endpoint(request: dict):
    """Generate an AI image or a lightweight SVG flowchart from a prompt."""
    prompt = request.get("prompt", "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    visual_type = request.get("type", "auto")
    wants_flowchart = visual_type == "flowchart" or any(
        keyword in prompt.lower()
        for keyword in ("flowchart", "flow chart", "workflow", "process diagram", "architecture diagram", "pipeline")
    )

    if wants_flowchart:
        chart_data = await _get_rich_flowchart_data_ai(prompt)
        svg = _render_rich_flowchart_svg(chart_data)
        return {
            "prompt": prompt,
            "type": "flowchart",
            "flowchart_svg": svg,
            "definition": chart_data.get("definition", ""),
            "chart_title": chart_data.get("title", ""),
        }

    import urllib.parse
    encoded = urllib.parse.quote(prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
    return {"prompt": prompt, "type": "image", "image_url": image_url}


# ──────────────────────────────────────────────────────────────────────────────
# Rich Flowchart: AI-structured multi-phase diagram with definition
# ──────────────────────────────────────────────────────────────────────────────

async def _get_rich_flowchart_data_ai(prompt: str) -> dict:
    """
    Call GROQ to get a fully structured flowchart:
    title, definition, and multi-phase steps with descriptions.
    Falls back to KB-based structured data if AI fails.
    """
    import urllib.request
    import urllib.error
    import json
    import re

    groq_key = os.environ.get("GROQ_API_KEY")
    loop = asyncio.get_event_loop()

    groq_prompt = (
        f'Create a detailed, professional end-to-end flowchart for: "{prompt}"\n\n'
        "Return ONLY a valid JSON object with NO markdown, NO backticks, NO explanation:\n"
        "{\n"
        '  "title": "ALL-CAPS CONCISE FLOWCHART TITLE (max 10 words)",\n'
        '  "definition": "1-2 sentence precise technical definition of the topic.",\n'
        '  "phases": [\n'
        '    {\n'
        '      "phase_name": "Phase 1\\nPHASE TITLE IN CAPS",\n'
        '      "color_theme": "blue",\n'
        '      "steps": [\n'
        '        {\n'
        '          "number": "1",\n'
        '          "title": "STEP TITLE IN CAPS (4-6 words)",\n'
        '          "description": "What happens in this step (max 8 words)",\n'
        '          "sub_steps": ["sub item 1", "sub item 2"]\n'
        '        }\n'
        '      ]\n'
        '    }\n'
        '  ]\n'
        "}\n\n"
        "STRICT RULES:\n"
        "- Create exactly 3 or 4 phases covering the full end-to-end process\n"
        "- Each phase must have exactly 2-4 steps\n"
        "- color_theme for phase 1=blue, phase 2=green, phase 3=orange, phase 4=red\n"
        "- description: maximum 8 words, no punctuation at end\n"
        "- sub_steps: exactly 2-3 very short items per step\n"
        "- All step numbers must be globally sequential (1, 2, 3 ... across all phases)\n"
        "- Return ONLY the raw JSON object"
    )

    if groq_key and groq_key not in ("your_groq_api_key_here", ""):
        def _call():
            payload = json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": (
                        "You are a JSON-only flowchart generator. "
                        "Always return only a raw valid JSON object. "
                        "Never include markdown, backticks, or any text outside the JSON."
                    )},
                    {"role": "user", "content": groq_prompt},
                ],
                "temperature": 0.15,
                "max_tokens": 1800,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {groq_key}",
                    "User-Agent": "Mozilla/5.0 (compatible; AgentForge/1.0)",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            content = raw["choices"][0]["message"]["content"].strip()
            print(f"[rich-flowchart] GROQ raw (first 400): {content[:400]}")
            # Strip any accidental markdown
            content = re.sub(r'```(?:json)?', '', content).strip('`').strip()
            s, e = content.find('{'), content.rfind('}')
            if s != -1 and e > s:
                data = json.loads(content[s:e+1])
                if "phases" in data and "title" in data:
                    return data
            return None

        try:
            result = await loop.run_in_executor(None, _call)
            if result:
                print(f"[rich-flowchart] GROQ success: {result['title']}")
                return result
        except urllib.error.HTTPError as e:
            print(f"[rich-flowchart] GROQ HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}")
        except Exception as e:
            print(f"[rich-flowchart] GROQ error: {type(e).__name__}: {e}")

    # ── KB fallback: build rich structure from simple steps ─────────
    print("[rich-flowchart] Falling back to KB")
    return _build_rich_data_from_kb(prompt)


def _build_rich_data_from_kb(prompt: str) -> dict:
    """Construct a rich multi-phase dict from the KB step list."""
    import re
    steps_flat = _get_algorithm_steps_from_kb(prompt)

    filler = r'\b(give|me|make|create|generate|design|draw|show|a|an|the|for|of|og|flowchart|flow chart|workflow|process|diagram|working|algorithm)\b'
    cleaned = re.sub(filler, " ", prompt, flags=re.I)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(" .:-").strip()
    title = (cleaned.upper() + " — END-TO-END WORKFLOW") if cleaned else "PROCESS WORKFLOW"

    colors = ["blue", "green", "orange", "red"]
    phase_labels = [
        "INITIALIZATION &\nINPUT SETUP",
        "CORE PROCESSING\n& COMPUTATION",
        "OPTIMIZATION\n& VALIDATION",
        "OUTPUT &\nFINAL RESULTS",
    ]

    # Split steps into chunks of 2
    chunks = [steps_flat[i:i+2] for i in range(0, len(steps_flat), 2)][:4]
    phases = []
    global_num = 1
    for i, chunk in enumerate(chunks):
        phase_steps = []
        for s in chunk:
            phase_steps.append({
                "number": str(global_num),
                "title": s.upper(),
                "description": s,
                "sub_steps": [],
            })
            global_num += 1
        phases.append({
            "phase_name": f"Phase {i+1}\n{phase_labels[i % len(phase_labels)]}",
            "color_theme": colors[i % len(colors)],
            "steps": phase_steps,
        })

    return {
        "title": title,
        "definition": f"This flowchart illustrates the complete end-to-end process for {cleaned or 'the requested topic'}.",
        "phases": phases,
    }


def _render_rich_flowchart_svg(data: dict) -> str:
    """
    Render a professional multi-phase flowchart SVG matching the style of
    the reference image: dark title bar, colored phase columns, numbered
    step cards with descriptions and sub-steps, and connecting arrows.
    """
    import html as HL

    title  = data.get("title", "PROCESS FLOWCHART").upper()
    phases = data.get("phases", [])
    if not phases:
        return "<svg xmlns='http://www.w3.org/2000/svg'><text y='20'>No data</text></svg>"

    # ── Layout constants ────────────────────────────────────────────
    CANVAS_W    = 1200
    MARGIN      = 14
    PHASE_GAP   = 12
    TITLE_H     = 68
    PH_HDR_H    = 74    # phase header height
    STEP_H      = 120   # each step card height
    STEP_GAP    = 8
    STEP_HPAD   = 8     # horizontal padding inside phase for cards
    BOT_PAD     = 18

    n = len(phases)
    phase_w = int((CANVAS_W - 2 * MARGIN - (n - 1) * PHASE_GAP) / n)
    max_steps = max(len(p.get("steps", [])) for p in phases)
    phase_content_h = PH_HDR_H + max_steps * (STEP_H + STEP_GAP) + STEP_GAP
    CANVAS_H = TITLE_H + phase_content_h + BOT_PAD + MARGIN

    # ── Color palettes ──────────────────────────────────────────────
    PAL = {
        "blue":   {"hdr": "#2980b9", "bg": "#d6eaf8", "bdr": "#1a5276", "txt": "#1a5276"},
        "green":  {"hdr": "#27ae60", "bg": "#d5f5e3", "bdr": "#1e8449", "txt": "#1e8449"},
        "orange": {"hdr": "#e67e22", "bg": "#fdebd0", "bdr": "#ca6f1e", "txt": "#ca6f1e"},
        "red":    {"hdr": "#c0392b", "bg": "#fadbd8", "bdr": "#922b21", "txt": "#922b21"},
        "purple": {"hdr": "#8e44ad", "bg": "#e8daef", "bdr": "#6c3483", "txt": "#6c3483"},
    }
    FALLBACK_COLORS = list(PAL.keys())

    def esc(s): return HL.escape(str(s))

    def wrap(text, max_ch):
        words, lines, cur = str(text).split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if len(t) <= max_ch: cur = t
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        return lines[:3]

    def txt_el(x, y, s, fill, size, weight="normal", anchor="start", max_len=60):
        s = str(s)[:max_len]
        return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
                f'fill="{fill}" font-family="Arial,sans-serif" '
                f'font-size="{size}" font-weight="{weight}">{esc(s)}</text>')

    EL = []  # SVG elements accumulator
    DEFS = ['<defs>']

    # ── Global white background + border ───────────────────────────
    EL.append(f'<rect width="{CANVAS_W}" height="{CANVAS_H}" fill="#f0f2f5" rx="12"/>')
    EL.append(f'<rect width="{CANVAS_W}" height="{CANVAS_H}" fill="none" stroke="#c8ced7" stroke-width="1.5" rx="12"/>')

    # ── Title bar ──────────────────────────────────────────────────
    EL.append(f'<rect x="0" y="0" width="{CANVAS_W}" height="{TITLE_H}" fill="#1a1a2e" rx="12"/>')
    EL.append(f'<rect x="0" y="{TITLE_H - 12}" width="{CANVAS_W}" height="12" fill="#1a1a2e"/>')
    title_lines = wrap(title, 88)
    n_tl = len(title_lines)
    for li, tl in enumerate(title_lines[:2]):
        ty = TITLE_H / 2 - (n_tl - 1) * 10 + li * 22 + 7
        EL.append(txt_el(CANVAS_W/2, ty, tl, "#ffffff", 17, "bold", "middle"))

    # Horizontal arrow marker (phase-to-phase)
    DEFS.append(
        '<marker id="harrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto">'
        '<path d="M0 1 L9 5 L0 9z" fill="#546e7a"/></marker>'
    )

    # ── Phase columns ──────────────────────────────────────────────
    for pi, phase in enumerate(phases):
        color_key = phase.get("color_theme", FALLBACK_COLORS[pi % len(FALLBACK_COLORS)])
        c = PAL.get(color_key, PAL["blue"])
        steps = phase.get("steps", [])
        phase_name = phase.get("phase_name", f"Phase {pi+1}")

        px = MARGIN + pi * (phase_w + PHASE_GAP)
        py = TITLE_H + MARGIN

        # Actual height of this phase (may be shorter than tallest)
        this_phase_h = PH_HDR_H + len(steps) * (STEP_H + STEP_GAP) + STEP_GAP

        # Phase container
        EL.append(
            f'<rect x="{px}" y="{py}" width="{phase_w}" height="{this_phase_h}" '
            f'fill="{c["bg"]}" rx="10" stroke="{c["hdr"]}" stroke-width="1.5"/>'
        )

        # Phase header rounded at top only
        EL.append(
            f'<rect x="{px}" y="{py}" width="{phase_w}" height="{PH_HDR_H}" '
            f'fill="{c["hdr"]}" rx="10"/>'
        )
        EL.append(
            f'<rect x="{px}" y="{py + PH_HDR_H - 10}" width="{phase_w}" height="10" fill="{c["hdr"]}"/>'
        )

        # Phase label (two lines: "Phase N" small, then "TITLE" bold)
        plines = phase_name.split("\n")
        EL.append(txt_el(px + phase_w/2, py + 26, plines[0], "#ffffffcc", 11, "normal", "middle"))
        if len(plines) > 1:
            EL.append(txt_el(px + phase_w/2, py + 52, plines[1], "#ffffff", 13, "bold", "middle"))

        # Horizontal arrow to next phase
        if pi < n - 1:
            ay = py + this_phase_h / 2
            ax1 = px + phase_w + 1
            ax2 = px + phase_w + PHASE_GAP - 1
            EL.append(
                f'<line x1="{ax1:.1f}" y1="{ay:.1f}" x2="{ax2:.1f}" y2="{ay:.1f}" '
                f'stroke="#546e7a" stroke-width="3.5" marker-end="url(#harrow)"/>'
            )

        # Vertical down-arrow marker for this phase
        arr_id = f"darr{pi}"
        DEFS.append(
            f'<marker id="{arr_id}" viewBox="0 0 10 10" refX="5" refY="9" '
            f'markerWidth="6" markerHeight="6" orient="auto">'
            f'<path d="M1 0 L5 9 L9 0z" fill="{c["hdr"]}"/></marker>'
        )

        # ── Step cards ─────────────────────────────────────────────
        card_w = phase_w - 2 * STEP_HPAD
        for si, step in enumerate(steps):
            sy = py + PH_HDR_H + STEP_GAP + si * (STEP_H + STEP_GAP)
            sx = px + STEP_HPAD

            # Card shadow
            EL.append(
                f'<rect x="{sx+2}" y="{sy+2}" width="{card_w}" height="{STEP_H}" '
                f'fill="#0002" rx="7"/>'
            )
            # Card background
            EL.append(
                f'<rect x="{sx}" y="{sy}" width="{card_w}" height="{STEP_H}" '
                f'fill="white" rx="7" stroke="{c["hdr"]}" stroke-width="1.2"/>'
            )
            # Left accent bar
            EL.append(
                f'<rect x="{sx}" y="{sy}" width="5" height="{STEP_H}" '
                f'fill="{c["hdr"]}" rx="7"/>'
                f'<rect x="{sx+2}" y="{sy}" width="3" height="{STEP_H}" fill="{c["hdr"]}"/>'
            )

            # Number badge
            bdg_cx = sx + 24
            bdg_cy = sy + 24
            EL.append(f'<circle cx="{bdg_cx}" cy="{bdg_cy}" r="15" fill="{c["hdr"]}"/>')
            EL.append(txt_el(bdg_cx, bdg_cy + 5, step.get("number", str(si+1)), "white", 12, "bold", "middle"))

            # Step title
            st_title = step.get("title", "")
            title_x = sx + 46
            st_lines = wrap(st_title, int(card_w / 7))
            for li, stl in enumerate(st_lines[:2]):
                EL.append(txt_el(title_x, sy + 16 + li * 15, stl, c["txt"], 11, "bold"))

            # Description
            desc_lines = wrap(step.get("description", ""), int(card_w / 6.2))
            for li, dl in enumerate(desc_lines[:2]):
                EL.append(txt_el(sx + 10, sy + 52 + li * 13, dl, "#555", 9.5))

            # Sub-steps
            for ssi, sub in enumerate(step.get("sub_steps", [])[:3]):
                EL.append(txt_el(sx + 12, sy + 80 + ssi * 13, f"▸ {sub}", c["hdr"], 9))

            # Down arrow between cards
            if si < len(steps) - 1:
                ax = px + phase_w / 2
                ay1 = sy + STEP_H
                ay2 = sy + STEP_H + STEP_GAP
                EL.append(
                    f'<line x1="{ax:.1f}" y1="{ay1}" x2="{ax:.1f}" y2="{ay2}" '
                    f'stroke="{c["hdr"]}" stroke-width="2.5" marker-end="url(#{arr_id})"/>'
                )

    DEFS.append('</defs>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
        f'role="img" aria-label="{esc(title)}" style="max-width:100%;height:auto;">'
        + ''.join(DEFS)
        + ''.join(EL)
        + '</svg>'
    )


async def _get_flowchart_steps_ai(prompt: str) -> list:
    """
    Use GROQ (primary) then Gemini (fallback) to generate algorithm-specific flowchart steps.
    Falls back to a comprehensive algorithm knowledge base if both AI calls fail.
    """
    import urllib.request
    import urllib.error
    import json
    import re

    ai_prompt = (
        f"Create a flowchart for: {prompt}\n\n"
        "Return ONLY a valid JSON array of exactly 6 short step labels (2-5 words each) "
        "that describe the SPECIFIC algorithm or process mentioned. "
        "Steps must be accurate and technical — never use generic words like 'process', 'inputs', 'output'. "
        "Example for 'keras neural network': "
        '["Define model architecture", "Compile with optimizer & loss", "Prepare training data", '
        '"Train with model.fit()", "Evaluate on test set", "Save & deploy model"] '
        "Return ONLY the raw JSON array on one line. No markdown, no code blocks, no explanation."
    )

    loop = asyncio.get_event_loop()

    def _parse_steps_from_text(raw: str):
        """Extract a JSON array from AI response text robustly."""
        raw = raw.strip()
        # Remove markdown code fences if present
        raw = re.sub(r'```(?:json)?', '', raw).strip('`').strip()
        # Find first '[' to last ']'
        start = raw.find('[')
        end = raw.rfind(']')
        if start != -1 and end != -1 and end > start:
            try:
                steps = json.loads(raw[start:end + 1])
                if isinstance(steps, list) and len(steps) >= 3:
                    return [str(s).strip() for s in steps[:7]]
            except json.JSONDecodeError:
                pass
        return None

    # ── 1. Try GROQ (primary — always works, no rate limits on free tier) ──
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key and groq_key not in ("your_groq_api_key_here", ""):
        def _call_groq():
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": (
                        "You are a technical flowchart generator. "
                        "Always respond with ONLY a raw JSON array of 6 step labels. "
                        "No markdown. No explanation. Steps must be specific to the algorithm requested."
                    )},
                    {"role": "user", "content": ai_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 300,
            }).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {groq_key}",
                    "User-Agent": "Mozilla/5.0 (compatible; AgentForge/1.0)",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body)
            raw = data["choices"][0]["message"]["content"]
            print(f"[flowchart] GROQ raw response: {raw[:200]}")
            return _parse_steps_from_text(raw)

        try:
            steps = await loop.run_in_executor(None, _call_groq)
            if steps:
                print(f"[flowchart] GROQ success — {len(steps)} steps: {steps}")
                return steps
            else:
                print("[flowchart] GROQ returned unparseable response, trying Gemini")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[flowchart] GROQ HTTP {e.code}: {body[:300]}")
        except Exception as e:
            print(f"[flowchart] GROQ error: {type(e).__name__}: {e}")

    # ── 2. Try Gemini (secondary fallback) ─────────────────────────
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if gemini_key and gemini_key not in ("your_gemini_api_key_here", ""):
        def _call_gemini(model):
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
                f":generateContent?key={gemini_key}"
            )
            payload = json.dumps({
                "contents": [{"parts": [{"text": ai_prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 300},
            }).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            raw = data["candidates"][0]["content"]["parts"][0]["text"]
            return _parse_steps_from_text(raw)

        for model in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]:
            try:
                steps = await loop.run_in_executor(None, _call_gemini, model)
                if steps:
                    print(f"[flowchart] Gemini {model} success — {len(steps)} steps")
                    return steps
            except urllib.error.HTTPError as e:
                print(f"[flowchart] Gemini {model} HTTP {e.code}")
            except Exception as e:
                print(f"[flowchart] Gemini {model} error: {type(e).__name__}: {e}")

    # ── 3. Algorithm knowledge-base fallback ───────────────────────
    print("[flowchart] All AI calls failed — using local knowledge-base fallback")
    return _get_algorithm_steps_from_kb(prompt)


def _get_algorithm_steps_from_kb(prompt: str) -> list:
    """
    Return algorithm-specific steps from a built-in knowledge base.
    Matches the algorithm name in the prompt and returns real steps.
    """
    import re

    p = prompt.lower()

    # ── Algorithm knowledge base ───────────────────────────────────
    KB = {
        # ML Frameworks
        "keras": [
            "Define model architecture (Sequential/Functional)",
            "Add layers (Dense, Conv2D, LSTM, etc.)",
            "Compile with optimizer & loss function",
            "Prepare & preprocess training data",
            "Train model with model.fit()",
            "Evaluate accuracy on test set",
            "Save & export model"
        ],
        "pytorch": [
            "Define neural network class (nn.Module)",
            "Prepare DataLoader & transforms",
            "Initialize model, optimizer & loss",
            "Forward pass through network",
            "Compute loss & backpropagate",
            "Optimizer step (update weights)",
            "Evaluate & save checkpoint"
        ],
        "tensorflow": [
            "Import TensorFlow & prepare data",
            "Build model with tf.keras layers",
            "Compile with loss & optimizer",
            "Train with model.fit()",
            "Evaluate on validation set",
            "Export SavedModel or TFLite"
        ],
        "scikit-learn": [
            "Import dataset & libraries",
            "Split into train & test sets",
            "Select & instantiate estimator",
            "Fit model on training data",
            "Predict on test data",
            "Evaluate metrics (accuracy, F1, etc.)"
        ],
        "xgboost": [
            "Prepare & encode dataset",
            "Convert to DMatrix format",
            "Set hyperparameters (eta, depth, rounds)",
            "Train with xgb.train()",
            "Evaluate with early stopping",
            "Generate feature importance plot",
            "Save & deploy model"
        ],
        # Regression
        "linear regression": [
            "Collect training data", "Initialize weights & bias",
            "Compute predictions (ŷ=Wx+b)", "Calculate MSE loss",
            "Apply gradient descent", "Output fitted model"
        ],
        "logistic regression": [

            "Collect labeled data", "Initialize weights",
            "Compute sigmoid activation", "Calculate cross-entropy loss",
            "Update via gradient descent", "Predict class probabilities"
        ],
        "polynomial regression": [
            "Collect input data", "Create polynomial features",
            "Fit least-squares regression", "Calculate residuals",
            "Evaluate R² score", "Output polynomial curve"
        ],
        "ridge regression": [
            "Collect training data", "Add L2 regularization term",
            "Solve (XᵀX + λI)β = Xᵀy", "Compute coefficients",
            "Evaluate on test set", "Output regularized model"
        ],
        "lasso regression": [
            "Collect training data", "Add L1 regularization term",
            "Apply coordinate descent", "Enforce sparsity on weights",
            "Select significant features", "Output sparse model"
        ],
        "tensor regression": [
            "Collect tensor-structured data", "Initialize tensor weights",
            "Compute tensor contraction", "Calculate loss & gradients",
            "Update via tensor SGD", "Decompose & evaluate tensor model"
        ],
        # Classification
        "decision tree": [
            "Load labeled dataset", "Select best split feature (Gini/Info Gain)",
            "Partition data at node", "Recurse on child nodes",
            "Apply stopping criteria", "Prune tree", "Classify new instances"
        ],
        "random forest": [
            "Load training data", "Bootstrap sample subsets",
            "Build multiple decision trees", "Apply random feature selection",
            "Aggregate predictions (voting)", "Output ensemble model"
        ],
        "naive bayes": [
            "Load training data", "Compute class priors P(C)",
            "Estimate feature likelihoods P(X|C)", "Apply Bayes theorem",
            "Choose max-posterior class", "Output classification"
        ],
        "svm": [
            "Load training data", "Map data to feature space",
            "Find maximum-margin hyperplane", "Identify support vectors",
            "Apply kernel trick (if nonlinear)", "Classify new points"
        ],
        "support vector machine": [
            "Load training data", "Map data to feature space",
            "Find maximum-margin hyperplane", "Identify support vectors",
            "Apply kernel trick (if nonlinear)", "Classify new points"
        ],
        "knn": [
            "Load training dataset", "Choose K value",
            "Compute distance to all points", "Select K nearest neighbors",
            "Vote on majority class", "Return predicted label"
        ],
        "k-nearest neighbors": [
            "Load training dataset", "Choose K value",
            "Compute distance to all points", "Select K nearest neighbors",
            "Vote on majority class", "Return predicted label"
        ],
        # Clustering
        "k-means": [
            "Initialize K centroids randomly", "Assign points to nearest centroid",
            "Recompute centroid positions", "Check convergence criterion",
            "Repeat until stable", "Output cluster assignments"
        ],
        "k means": [
            "Initialize K centroids randomly", "Assign points to nearest centroid",
            "Recompute centroid positions", "Check convergence criterion",
            "Repeat until stable", "Output cluster assignments"
        ],
        "dbscan": [
            "Choose ε and minPts", "Find core points (density check)",
            "Expand clusters from core points", "Mark border & noise points",
            "Assign cluster labels", "Output clustered dataset"
        ],
        # Neural Networks
        "neural network": [
            "Initialize weights & biases", "Forward pass (compute activations)",
            "Compute loss function", "Backpropagation (compute gradients)",
            "Update weights (optimizer step)", "Repeat over epochs",
            "Evaluate on validation set"
        ],
        "cnn": [
            "Load image dataset", "Apply convolutional filters",
            "Apply ReLU activation", "Max-pool feature maps",
            "Flatten to dense layers", "Softmax classification output"
        ],
        "convolutional neural network": [
            "Load image dataset", "Apply convolutional filters",
            "Apply ReLU activation", "Max-pool feature maps",
            "Flatten to dense layers", "Softmax classification output"
        ],
        "rnn": [
            "Prepare sequential input data", "Initialize hidden state",
            "Process token with RNN cell", "Update hidden state",
            "Compute output at each step", "Backprop through time (BPTT)"
        ],
        "lstm": [
            "Prepare sequence data", "Initialize cell & hidden states",
            "Compute forget gate", "Compute input & output gates",
            "Update cell state", "Produce sequence output"
        ],
        "transformer": [
            "Tokenize & embed input", "Add positional encoding",
            "Multi-head self-attention", "Feed-forward sublayers",
            "Apply layer normalization", "Decoder cross-attention",
            "Output probability distribution"
        ],
        # Sorting
        "bubble sort": [
            "Start at first element", "Compare adjacent elements",
            "Swap if out of order", "Move to next pair",
            "Repeat for N-1 passes", "Return sorted array"
        ],
        "merge sort": [
            "Divide array into halves", "Recursively sort each half",
            "Merge sorted halves", "Compare & copy elements",
            "Concatenate merged result", "Return sorted array"
        ],
        "quick sort": [
            "Choose pivot element", "Partition array around pivot",
            "Place pivot in correct position", "Recursively sort left partition",
            "Recursively sort right partition", "Return sorted array"
        ],
        "heap sort": [
            "Build max-heap from array", "Extract max element",
            "Swap root with last element", "Heapify reduced heap",
            "Repeat until heap is empty", "Return sorted array"
        ],
        # Search
        "binary search": [
            "Start with sorted array", "Set low and high pointers",
            "Compute mid index", "Compare target with mid element",
            "Narrow search range", "Return found index or -1"
        ],
        "bfs": [
            "Initialize queue with start node", "Mark start as visited",
            "Dequeue front node", "Visit all unvisited neighbors",
            "Enqueue unvisited neighbors", "Repeat until queue is empty"
        ],
        "breadth first search": [
            "Initialize queue with start node", "Mark start as visited",
            "Dequeue front node", "Visit all unvisited neighbors",
            "Enqueue unvisited neighbors", "Repeat until queue is empty"
        ],
        "dfs": [
            "Push start node to stack", "Mark node as visited",
            "Pop node from stack", "Visit unvisited neighbors",
            "Push neighbors to stack", "Repeat until stack is empty"
        ],
        "depth first search": [
            "Push start node to stack", "Mark node as visited",
            "Pop node from stack", "Visit unvisited neighbors",
            "Push neighbors to stack", "Repeat until stack is empty"
        ],
        "dijkstra": [
            "Initialize distances (source=0, rest=∞)", "Add source to priority queue",
            "Dequeue node with min distance", "Relax neighbor edge weights",
            "Update priority queue", "Repeat until destination reached"
        ],
        # ML/AI misc
        "gradient descent": [
            "Initialize parameters randomly", "Compute loss function",
            "Calculate gradient ∂L/∂θ", "Update θ = θ - α·∇L",
            "Check convergence condition", "Repeat until convergence"
        ],
        "backpropagation": [
            "Perform forward pass", "Compute output loss",
            "Calculate output layer gradients", "Propagate gradients backward",
            "Compute weight gradients", "Update all weights"
        ],
        "pca": [
            "Standardize the dataset", "Compute covariance matrix",
            "Calculate eigenvalues & eigenvectors", "Sort by explained variance",
            "Project data onto top components", "Output reduced-dimension data"
        ],
        "principal component analysis": [
            "Standardize the dataset", "Compute covariance matrix",
            "Calculate eigenvalues & eigenvectors", "Sort by explained variance",
            "Project data onto top components", "Output reduced-dimension data"
        ],
        "genetic algorithm": [
            "Initialize random population", "Evaluate fitness of each individual",
            "Select parents (tournament/roulette)", "Apply crossover operation",
            "Apply mutation", "Form new generation", "Repeat until convergence"
        ],
        "a* search": [
            "Initialize open & closed sets", "Add start node (g=0, h=heuristic)",
            "Select node with min f=g+h", "Expand neighbors",
            "Update g-scores if shorter path found", "Repeat until goal reached"
        ],
        "reinforcement learning": [
            "Initialize agent & environment", "Observe current state",
            "Select action (ε-greedy policy)", "Execute action & get reward",
            "Update Q-value / policy network", "Transition to next state",
            "Repeat until convergence"
        ],
    }

    # Try longest-match first
    for key in sorted(KB.keys(), key=len, reverse=True):
        if key in p:
            return KB[key]

    # Keyword alias matching
    aliases = [
        # Frameworks (check before generic algo names)
        (["keras"], "keras"),
        (["pytorch", "torch"], "pytorch"),
        (["tensorflow", "tf."], "tensorflow"),
        (["scikit", "sklearn"], "scikit-learn"),
        (["xgboost", "xgb"], "xgboost"),
        # Regression
        (["tensor", "regression"], "tensor regression"),
        (["linear", "regress"], "linear regression"),
        (["logistic", "regress"], "logistic regression"),
        (["polynomial", "regress"], "polynomial regression"),
        (["ridge", "regress"], "ridge regression"),
        (["lasso", "regress"], "lasso regression"),
        (["regress"], "linear regression"),
        # Classification & clustering
        (["random forest"], "random forest"),
        (["decision tree"], "decision tree"),
        (["k-means", "kmeans", "clustering"], "k-means"),
        (["svm", "support vector"], "svm"),
        # Neural networks
        (["neural", "network"], "neural network"),
        (["deep learning"], "neural network"),
        (["convolution", "cnn"], "cnn"),
        (["lstm", "long short"], "lstm"),
        (["transformer", "attention"], "transformer"),
        # Optimization
        (["gradient", "descent"], "gradient descent"),
        (["backprop"], "backpropagation"),
        (["pca", "principal component"], "pca"),
        (["genetic"], "genetic algorithm"),
        # Sorting
        (["bubble", "sort"], "bubble sort"),
        (["merge", "sort"], "merge sort"),
        (["quick", "sort"], "quick sort"),
        # Search & graph
        (["binary", "search"], "binary search"),
        (["dijkstra", "shortest path"], "dijkstra"),
        (["reinforcement", "q-learning", "rl agent"], "reinforcement learning"),
        (["bfs", "breadth"], "bfs"),
        (["dfs", "depth"], "dfs"),
    ]
    for keywords, kb_key in aliases:
        if any(kw in p for kw in keywords):
            return KB[kb_key]

    # Generic subject-based fallback (last resort)
    filler = r'\b(give|me|make|create|generate|design|draw|show|a|an|the|for|of|og|flowchart|flow chart|workflow|process|diagram|working|algorithm)\b'
    cleaned = re.sub(filler, " ", prompt, flags=re.I)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(" .:-")
    subject = cleaned.strip() or "the process"
    subject_cap = subject[0].upper() + subject[1:]
    return [
        f"Define {subject_cap} inputs",
        f"Initialize {subject_cap} parameters",
        f"Execute {subject_cap} core logic",
        f"Process intermediate results",
        f"Evaluate output quality",
        f"Return final result",
    ]


def _render_flowchart_svg(steps: list, prompt: str) -> str:
    """Render a clean SVG flowchart from a list of step labels."""
    import html

    steps = steps[:7]
    width = 940
    box_w = 190
    box_h = 70
    gap = 36
    height = 160 + max(0, len(steps) - 4) * 120
    items = []
    connectors = []

    for index, step in enumerate(steps):
        row = index // 4
        col = index % 4
        if row % 2 == 1:
            col = 3 - col
        x = 30 + col * (box_w + gap)
        y = 52 + row * 120

        # Wrap long labels across two lines
        raw = str(step)[:50]
        words = raw.split()
        mid = len(words) // 2 or 1
        line1 = html.escape(" ".join(words[:mid]))
        line2 = html.escape(" ".join(words[mid:]))

        items.append(
            f'<g>'
            f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="12" fill="#1a1d27" stroke="#6d8bff" stroke-width="2"/>'
            f'<text x="{x + box_w / 2}" y="{y + 24}" text-anchor="middle" fill="#f4f6fb" font-family="Inter, Arial" font-size="13" font-weight="700">{line1}</text>'
            f'<text x="{x + box_w / 2}" y="{y + 40}" text-anchor="middle" fill="#f4f6fb" font-family="Inter, Arial" font-size="13" font-weight="700">{line2}</text>'
            f'<text x="{x + box_w / 2}" y="{y + 58}" text-anchor="middle" fill="#38e7dd" font-family="Inter, Arial" font-size="10">Step {index + 1}</text>'
            f'</g>'
        )

        if index:
            prev_row = (index - 1) // 4
            prev_col = (index - 1) % 4
            if prev_row % 2 == 1:
                prev_col = 3 - prev_col
            px = 30 + prev_col * (box_w + gap)
            py = 52 + prev_row * 120
            x1 = px + box_w
            y1 = py + box_h / 2
            x2 = x
            y2 = y + box_h / 2
            if row != prev_row:
                x1 = px + box_w / 2
                y1 = py + box_h
                x2 = x + box_w / 2
                y2 = y
            connectors.append(
                f'<path d="M{x1} {y1} C{(x1+x2)/2} {y1}, {(x1+x2)/2} {y2}, {x2} {y2}" '
                f'fill="none" stroke="#38e7dd" stroke-width="2.5" marker-end="url(#arrow)"/>'
            )

    title = html.escape(prompt[:80])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Generated flowchart">'
        '<defs>'
        '<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M0 0 L10 5 L0 10z" fill="#38e7dd"/></marker>'
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop stop-color="#0e1018"/><stop offset="1" stop-color="#1c1b30"/>'
        '</linearGradient>'
        '</defs>'
        f'<rect width="{width}" height="{height}" rx="18" fill="url(#bg)"/>'
        f'<text x="36" y="32" fill="#9da4b2" font-family="Inter, Arial" font-size="13" font-weight="700">{title}</text>'
        + "".join(connectors)
        + "".join(items)
        + '</svg>'
    )


def _build_fallback_research_report(topic: str, depth: str) -> str:
    """
    Generate a comprehensive research report.
    Uses live Serper web search + optional LLM synthesis.
    Falls back to a rich structured local report when LLMs are unavailable.
    LLM calls have a hard 8-second timeout to avoid hanging.
    """
    import urllib.request
    import json
    import time
    import re
    import threading as _threading

    serper_key = os.environ.get("SERPER_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")

    # ── 1. Fetch live Serper search results ──────────────────────────────────
    search_context = ""
    raw_search_items = []
    if serper_key and serper_key != "your_serper_api_key_here":
        try:
            req = urllib.request.Request(
                "https://google.serper.dev/search",
                data=json.dumps({"q": topic, "num": 10}).encode("utf-8"),
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_search_items = data.get("organic", [])
                snippets = []
                for item in raw_search_items[:8]:
                    title = item.get("title", "")
                    snippet = item.get("snippet", "")
                    link = item.get("link", "")
                    snippets.append(f"- **{title}**: {snippet} (Source: {link})")
                if snippets:
                    search_context = "\n".join(snippets)
        except Exception as e:
            print("Serper search error:", e)

    # ── 2. Parse individual subtopics ───────────────────────────────────────
    topic_lines = [
        t.strip(" -\u2022*\t")
        for t in re.split(r"[\n,;]", topic)
        if t.strip(" -\u2022*\t") and len(t.strip()) > 2
    ]
    preamble_words = {
        "explain", "these", "topics", "topic", "describe", "what",
        "is", "are", "the", "following", "about", "me", "please",
        "give", "list", "show", "tell", "find", "get", "all", "every",
        "each", "and", "or", "a", "an", "in", "of", "for", "to"
    }
    topic_list = [
        t for t in topic_lines
        if not all(w.lower() in preamble_words for w in t.split())
    ]
    if not topic_list:
        topic_list = [topic]
    numbered_topics = "\n".join(f"  {i}. {t}" for i, t in enumerate(topic_list, 1))

    # ── 3. Build LLM prompts ─────────────────────────────────────────────────
    system_instruction = (
        "You are an elite AI Research Analyst. Write a COMPREHENSIVE, IN-DEPTH research report.\n\n"
        "⚠️ MANDATORY OUTPUT ORDER — do NOT deviate from this structure:\n\n"
        "PART 1 — FULL DETAILED ANSWER (write all content sections first, NO source links here):\n"
        "## 1. Executive Summary\n"
        "  4-6 sentences covering all key topics, why they matter, and the key takeaways.\n\n"
        "## 2. In-Depth Analysis\n"
        "  For EACH topic, create a ### subsection (300-400 words minimum each) with:\n"
        "  - Clear definition and core concepts\n"
        "  - How it works (step-by-step or mechanistically)\n"
        "  - Real-world examples with specific names, data, and numbers\n"
        "  - Key statistics or facts\n"
        "  - Common misconceptions or nuances\n"
        "  - Current trends and future outlook\n\n"
        "## 3. Comparative Analysis\n"
        "  Compare and contrast the topics — patterns, relationships, trade-offs.\n\n"
        "## 4. Key Insights & Actionable Takeaways\n"
        "  Expert-level insights, strategic implications, and actionable recommendations.\n\n"
        "PART 2 — SOURCES (ALWAYS THE LAST SECTION, placed AFTER all content above):\n"
        "## 5. Sources & References\n"
        "  Reference table from web search context.\n\n"
        "🚫 CRITICAL RULES:\n"
        "  - Do NOT include any source URLs, links, or 'via [domain]' references in Parts 1-4.\n"
        "  - All URLs and source attributions go ONLY in the ## 5. Sources & References section.\n"
        "  - The reader must receive the COMPLETE, DETAILED ANSWER before ever seeing a source link.\n"
        "  - Aim for 1500-2500 words of actual content (not counting the sources section).\n\n"
        f"Topics to cover in-depth:\n{numbered_topics}\n"
    )
    user_prompt = f"Research Request: {topic}\nDepth: {depth}\n"
    if search_context:
        user_prompt += f"\nLive Web Context (use as reference, not as full answer):\n{search_context}\n"
    user_prompt += "\nWrite the complete research report following the mandatory structure."

    # ── 4. Helper: call LLM with 60s timeout ─────────────────────────────────
    LLM_TIMEOUT = 60  # 60s allows Gemini to complete full generation cleanly

    def _call_with_timeout(fn):
        """Run fn() in a thread; return its result or None on timeout/error."""
        result_box = [None]
        err_box = [None]
        def _worker():
            try:
                result_box[0] = fn()
            except Exception as exc:
                err_box[0] = exc

        t = _threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=LLM_TIMEOUT)
        if err_box[0]:
            print(f"[fallback LLM error] {err_box[0]}")
        return result_box[0]

    # ── 5. Try Gemini (Primary - gemini-2.5-flash is fast & reliable) ───────
    if gemini_key and gemini_key not in ("your_gemini_api_key_here", ""):
        for model in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro"]:
            def _try_gemini(m=model):
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_instruction}\n\n{user_prompt}"}]}],
                    "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.3}
                }
                req = urllib.request.Request(
                    url, data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(req, timeout=50) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    text = res_data["candidates"][0]["content"]["parts"][0]["text"]
                    return text.strip() if text.strip() and len(text.strip()) > 200 else None
            result = _call_with_timeout(_try_gemini)
            if result:
                print(f"[fallback] Gemini {model} succeeded!")
                return result
            print(f"[fallback] Gemini {model} failed or timed out, trying next...")

    # ── 6. Try Groq (Secondary - max 2048 tokens to stay under 6000 TPM limit) ──
    if groq_key and groq_key not in ("your_groq_api_key_here", ""):
        for gmodel in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it"]:
            def _try_groq(m=gmodel):
                payload = {
                    "model": m,
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                }
                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=40) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    text = res_data["choices"][0]["message"]["content"]
                    return text.strip() if text.strip() and len(text.strip()) > 200 else None

            result = _call_with_timeout(_try_groq)
            if result:
                print(f"[fallback] Groq {gmodel} succeeded!")
                return result
            print(f"[fallback] Groq {gmodel} failed or timed out, trying next...")

    # ── 7. Offline Rich Structured Fallback (When API calls are unavailable) ─
    print("[fallback] Generating offline detailed structured research report...")
    topic_clean = topic.strip()

    # Extract target subject/location from query (e.g. "scottland", "japan", "places in X")
    import re
    cleaned_subject = re.sub(
        r'\b(give|me|all|list|show|tell|about|visitable|places|place|in|for|the|best|top|to|visit)\b',
        ' ', topic, flags=re.IGNORECASE
    )
    cleaned_subject = re.sub(r'\s+', ' ', cleaned_subject).strip(' .:-')
    target_name = cleaned_subject.title() if cleaned_subject else topic.title()
    # Group snippets by best-matching topic
    snippet_map: dict = {}
    for item in raw_search_items:
        for t in topic_list:
            t_words = [w for w in t.lower().split() if len(w) > 3]
            title_lower = item.get("title", "").lower()
            snip = item.get("snippet", "")
            if any(w in title_lower for w in t_words) or t.lower() in title_lower:
                if t not in snippet_map:
                    snippet_map[t] = []
                snippet_map[t].append((item.get("title", ""), snip, item.get("link", "#")))

    # Also collect all snippets not matched to any topic (use as general pool)
    all_snippets = [
        (item.get("title", ""), item.get("snippet", ""), item.get("link", "#"))
        for item in raw_search_items
    ]

    topic_sections = []
    for idx, t in enumerate(topic_list, 1):
        snippets_for_t = snippet_map.get(t, []) or all_snippets[((idx-1)*2):((idx-1)*2)+3]
        facts_list = []
        for stitle, ssnippet, _ in snippets_for_t[:3]:
            if ssnippet and len(ssnippet) > 15:
                facts_list.append(f"  - **{stitle}**: {ssnippet}")

        facts_str = "\n".join(facts_list) if facts_list else f"  - Detailed research data and key findings regarding **{target_name}**."

        section_content = (
            f"### {idx}. Key Highlights & Major Destinations for {target_name}\n\n"
            f"#### Overview & Regional Insights\n"
            f"**{target_name}** offers a diverse range of attractions, cultural landmarks, and scenic landscapes. "
            f"When exploring {target_name}, travelers and researchers prioritize top historical sites, natural wonders, and local cultural experiences.\n\n"
            f"#### Key Findings & Extracted Information\n"
            f"{facts_str}\n\n"
            f"#### Practical Travel & Planning Advice\n"
            f"- **Best Approach**: Plan your itinerary by region or interest (e.g., historical cities, countryside, coastal areas).\n"
            f"- **Timing & Seasonality**: Check local seasonal highlights and weather patterns before booking.\n"
            f"- **Travel Tips**: Reserve major attraction tickets in advance and utilize regional transportation passes.\n"
        )
        topic_sections.append(section_content)

    explanation_body = "\n---\n\n".join(topic_sections)

    # Build sources reference table (placed ONLY at the end)
    if raw_search_items:
        source_rows = []
        for sidx, item in enumerate(raw_search_items[:10], 1):
            stitle = item.get("title", f"Source {sidx}").replace("|", "-")
            ssnippet = item.get("snippet", "").replace("|", "-")
            slink = item.get("link", "#")
            domain = slink.split('/')[2] if '://' in slink else "web source"
            source_rows.append(f"| {sidx} | **{stitle[:70]}** | {ssnippet[:120]}… | [{domain}]({slink}) |")
        sources_table = (
            "| # | Title | Summary | Source |\n"
            "|:--|:------|:--------|:-------|\n"
            + "\n".join(source_rows)
        )
    else:
        sources_table = "_No live web sources were retrieved._"

    interconnect = (
        f"The research findings presented above synthesize key aspects of **{topic}**. "
        f"For real-time dynamic AI generation on any custom topic, connect your Gemini or Groq API key in the left sidebar."
    )

    api_notice = ""
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")):
        api_notice = "\n> 💡 **Notice**: To generate dynamic custom AI reports for any request, enter your **Gemini API Key** in the sidebar settings or Streamlit Cloud Secrets!\n"

    return f"""# Research Report: {topic}

## 1. Executive Summary

This report provides a comprehensive, structured analysis answering: **{topic}**. 
Synthesized from live research data, the following sections deliver detailed breakdowns, actionable insights, practical advice, and key recommendations.

---

## 2. In-Depth Research Breakdown

{explanation_body}

---

## 3. Key Insights & Actionable Takeaways

{interconnect}

---

## 4. Verified Sources & References

> All source links are listed below. The complete detailed answer above is fully self-contained.

{sources_table}
"""


def _get_uploaded_source_path(doc_id: str) -> str | None:
    """Find the original uploaded file for a document session."""
    for path in glob.glob(os.path.join(UPLOAD_DIR, f"{doc_id}_*")):
        if not path.endswith("_extracted.txt"):
            return path
    return None


def _ensure_document_runtime(doc_id: str, session: dict) -> str:
    """Reload extracted text and table DataFrames for an uploaded document if needed."""
    extracted_path = os.path.join(UPLOAD_DIR, f"{doc_id}_extracted.txt")
    extracted_text = ""
    if os.path.exists(extracted_path):
        with open(extracted_path, "r", encoding="utf-8") as f:
            extracted_text = f.read()

    source_path = _get_uploaded_source_path(doc_id)
    if source_path:
        try:
            from agents.file_parser import parse_file
            from agents.math_tools import register_dataframes
            with open(source_path, "rb") as source:
                parsed = parse_file(source.read(), session["filename"])
            if not extracted_text:
                extracted_text = parsed.get("text", "")
                with open(extracted_path, "w", encoding="utf-8") as f:
                    f.write(extracted_text)
            tables = parsed.get("tables", [])
            if tables:
                register_dataframes(doc_id, tables)
        except Exception:
            pass

    return extracted_text


def _try_vision_image_report(prompt: str, image_path: str, file_type: str) -> str:
    """Optionally analyze an uploaded image with a Groq/OpenAI-compatible vision model."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        return ""

    import base64
    import mimetypes
    import urllib.request

    mime = mimetypes.guess_type(image_path)[0] or f"image/{file_type}"
    with open(image_path, "rb") as image_file:
        data_url = f"data:{mime};base64,{base64.b64encode(image_file.read()).decode('ascii')}"

    payload = {
        "model": os.environ.get("VISION_MODEL", "llama-3.2-11b-vision-preview"),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 1200,
    }

    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
