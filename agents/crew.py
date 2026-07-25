"""
AgentForge — Crew Orchestration Engine
Assembles agents and tasks into a CrewAI Crew, manages execution,
and captures real-time agent activity for streaming to the frontend.
"""

import time
import threading
import uuid
import os
import sys
from datetime import datetime
from typing import Optional
from io import StringIO
import contextlib
import re

# Force UTF-8 encoding on Windows to handle unicode symbols like ₹, emojis, etc.
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Disable CrewAI telemetry to avoid background thread crashes on Windows
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"

from crewai import Crew, Process

from agents.agents import create_all_agents
from agents.tasks import create_all_tasks


class AgentActivityLog:
    """Thread-safe activity log that captures agent actions in real-time."""

    def __init__(self):
        self._activities = []
        self._lock = threading.Lock()
        self._last_read_index = 0

    def add(self, agent_name: str, action: str, content: str = ""):
        """Record an agent activity."""
        with self._lock:
            self._activities.append({
                "id": str(uuid.uuid4())[:8],
                "agent": agent_name,
                "action": action,
                "content": content[:500],  # Truncate for SSE efficiency
                "timestamp": datetime.now().isoformat(),
            })

    def get_new(self):
        """Get activities added since last read (for SSE streaming)."""
        with self._lock:
            new_items = self._activities[self._last_read_index:]
            self._last_read_index = len(self._activities)
            return new_items

    def get_all(self):
        """Get all recorded activities."""
        with self._lock:
            return list(self._activities)


class ResearchCrew:
    """
    Manages the lifecycle of a research crew execution.
    Creates agents, assigns tasks, runs the crew, and logs activities.
    """

    # Map agent roles to display-friendly names and icons
    AGENT_DISPLAY = {
        "Research Strategist": {"icon": "🔍", "color": "#3b82f6"},
        "Web Research Specialist": {"icon": "🌐", "color": "#10b981"},
        "Data Analyst": {"icon": "📊", "color": "#f59e0b"},
        "Report Writer": {"icon": "📝", "color": "#8b5cf6"},
    }

    def __init__(self):
        self.activity_log = AgentActivityLog()
        self.status = "idle"  # idle | running | completed | failed
        self.result = None
        self.error = None
        self.start_time = None
        self.end_time = None

    def _step_callback(self, step_output):
        """
        CrewAI step callback — fires after each agent action.
        Captures the agent's thought process and tool usage.
        """
        try:
            # Extract agent info from the step
            agent_name = "System"
            action = "processing"
            content = ""

            if hasattr(step_output, 'agent') and step_output.agent:
                agent_name = step_output.agent
            
            if hasattr(step_output, 'output'):
                output_text = str(step_output.output)
                # Identify what type of action this is
                if "search" in output_text.lower() or "serper" in output_text.lower():
                    action = "searching the web"
                elif "scrape" in output_text.lower() or "website" in output_text.lower():
                    action = "scraping website content"
                elif "thought" in output_text.lower() or "think" in output_text.lower():
                    action = "thinking"
                else:
                    action = "processing"
                content = output_text[:500]

            self.activity_log.add(agent_name, action, content)
        except Exception:
            pass  # Don't let logging errors crash the crew

    def _task_callback(self, task_output):
        """
        CrewAI task callback — fires when a task is completed.
        Logs the transition between agents.
        """
        try:
            agent_name = "System"
            if hasattr(task_output, 'agent') and task_output.agent:
                agent_name = task_output.agent

            output_preview = ""
            if hasattr(task_output, 'raw'):
                output_preview = str(task_output.raw)[:300]

            self.activity_log.add(
                agent_name,
                "completed task",
                f"Task completed. Output preview: {output_preview}"
            )
        except Exception:
            pass

    def run(self, topic: str, depth: str = "detailed") -> dict:
        """
        Execute the full research pipeline synchronously.
        This is designed to be called from a background thread.
        
        Args:
            topic: The research topic
            depth: Research depth — "quick", "detailed", or "deep"
            
        Returns:
            dict with the research results and metadata
        """
        self.status = "running"
        self.start_time = datetime.now()

        self.activity_log.add("System", "initializing", f"Starting research on: {topic}")

        try:
            # 1. Create agents
            self.activity_log.add("System", "creating agents", "Assembling the research crew...")
            agents = create_all_agents()

            # 2. Create tasks
            self.activity_log.add("System", "creating tasks", f"Building {depth} research pipeline...")
            tasks = create_all_tasks(agents, topic, depth)

            # 3. Assemble crew with active agents for the selected depth
            active_agents = []
            for t in tasks:
                if t.agent not in active_agents:
                    active_agents.append(t.agent)

            self.activity_log.add("System", "assembling crew", f"All agents ready for {depth} mode. Starting execution...")
            crew = Crew(
                agents=active_agents,
                tasks=tasks,
                process=Process.sequential,
                verbose=True,
                step_callback=self._step_callback,
                task_callback=self._task_callback,
            )

            # 4. Log active agents starting
            for ag in active_agents:
                self.activity_log.add(ag.role, "queued", f"{ag.role} ready...")

            # 5. Execute the crew
            self.activity_log.add("Research Strategist", "starting", "Analyzing topic and creating research plan...")
            result = crew.kickoff()

            # 6. Process result
            self.end_time = datetime.now()
            duration = (self.end_time - self.start_time).total_seconds()

            # Extract the final report text
            report_text = ""
            if hasattr(result, 'raw'):
                report_text = result.raw
            elif isinstance(result, str):
                report_text = result
            else:
                report_text = str(result)

            self.result = {
                "topic": topic,
                "depth": depth,
                "report": report_text,
                "duration_seconds": round(duration, 1),
                "agents_used": list(self.AGENT_DISPLAY.keys()),
                "activity_count": len(self.activity_log.get_all()),
                "timestamp": self.end_time.isoformat(),
            }

            self.status = "completed"
            self.activity_log.add("System", "completed",
                f"Research completed in {round(duration, 1)}s with {len(self.activity_log.get_all())} agent actions.")

            return self.result

        except Exception as e:
            self.status = "failed"
            self.error = str(e)
            self.end_time = datetime.now()
            self.activity_log.add("System", "error", f"Research failed: {str(e)[:300]}")
            raise


    def cancel(self) -> bool:
        """Cancel an ongoing research task."""
        if self.status == "running":
            self.status = "cancelled"
            self.error = "Research task was cancelled by user."
            self.activity_log.add("System", "cancelled", "Research process was cancelled.")
            return True
        return False


# Global registry of active research sessions (in-memory)
_active_sessions: dict[str, ResearchCrew] = {}
_sessions_lock = threading.Lock()


def get_session(task_id: str) -> Optional[ResearchCrew]:
    """Get a research session by task ID."""
    with _sessions_lock:
        return _active_sessions.get(task_id)


def create_session(task_id: str) -> ResearchCrew:
    """Create and register a new research session."""
    session = ResearchCrew()
    with _sessions_lock:
        _active_sessions[task_id] = session
    return session


def remove_session(task_id: str) -> bool:
    """Evict a research session from in-memory storage after completion/cancellation."""
    with _sessions_lock:
        return _active_sessions.pop(task_id, None) is not None


def cleanup_stale_sessions(max_age_seconds: int = 3600):
    """Evict completed/failed/cancelled sessions older than max_age_seconds."""
    now = datetime.now()
    with _sessions_lock:
        to_delete = []
        for tid, session in _active_sessions.items():
            if session.status in ("completed", "failed", "cancelled") and session.end_time:
                if (now - session.end_time).total_seconds() > max_age_seconds:
                    to_delete.append(tid)
        for tid in to_delete:
            _active_sessions.pop(tid, None)


def list_sessions() -> list[dict]:
    """List all research sessions with their status."""
    with _sessions_lock:
        return [
            {
                "task_id": tid,
                "status": session.status,
                "start_time": session.start_time.isoformat() if session.start_time else None,
            }
            for tid, session in _active_sessions.items()
        ]

