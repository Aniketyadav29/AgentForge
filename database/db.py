"""
AgentForge — SQLite Database Operations
Persists research sessions, reports, and agent activity logs.
"""

import os
import json
import sqlite3
from typing import Optional, List, Dict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "agentforge.db")


def get_connection():
    """Get a SQLite connection with row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create database tables if they don't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE NOT NULL,
                topic TEXT NOT NULL,
                depth TEXT NOT NULL DEFAULT 'detailed',
                status TEXT NOT NULL DEFAULT 'pending',
                report TEXT,
                duration_seconds REAL,
                agents_used TEXT,
                activity_log TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS document_sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id     TEXT UNIQUE NOT NULL,
                filename   TEXT NOT NULL,
                file_type  TEXT NOT NULL,
                file_size  INTEGER,
                chunk_count INTEGER DEFAULT 0,
                has_tables  INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            )
        """)
        conn.commit()


def save_session(task_id: str, topic: str, depth: str, status: str = "pending"):
    """Save a new research session to the database."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO research_sessions (task_id, topic, depth, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, topic, depth, status, datetime.now().isoformat()),
        )
        conn.commit()


def update_session(
    task_id: str,
    status: str,
    report: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    agents_used: Optional[list] = None,
    activity_log: Optional[list] = None,
    error_message: Optional[str] = None,
):
    """Update a research session after completion or failure."""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE research_sessions
            SET status = ?,
                report = ?,
                duration_seconds = ?,
                agents_used = ?,
                activity_log = ?,
                error_message = ?,
                completed_at = ?
            WHERE task_id = ?
            """,
            (
                status,
                report,
                duration_seconds,
                json.dumps(agents_used) if agents_used else None,
                json.dumps(activity_log) if activity_log else None,
                error_message,
                datetime.now().isoformat(),
                task_id,
            ),
        )
        conn.commit()


def get_session_by_id(task_id: str) -> Optional[Dict]:
    """Get a research session by its task ID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM research_sessions WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row:
            return dict(row)
    return None


def get_all_sessions(limit: int = 50, offset: int = 0) -> List[Dict]:
    """Get all research sessions, ordered by most recent first."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, task_id, topic, depth, status, duration_seconds, 
                   agents_used, created_at, completed_at
            FROM research_sessions
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]


def get_sessions_count() -> int:
    """Get total count of research sessions in database."""
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM research_sessions").fetchone()
        return row[0] if row else 0


def delete_session(task_id: str) -> bool:
    """Delete a research session by task ID."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM research_sessions WHERE task_id = ?", (task_id,)
        )
        conn.commit()
        return cursor.rowcount > 0


# Initialize the database on module import
init_db()


# ─────────────────────────────────────────────────────────────────────────────
# Document Session CRUD
# ─────────────────────────────────────────────────────────────────────────────

def save_document_session(
    doc_id: str,
    filename: str,
    file_type: str,
    file_size: int,
    chunk_count: int,
    has_tables: bool,
):
    """Persist an uploaded document record."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO document_sessions
                (doc_id, filename, file_type, file_size, chunk_count, has_tables, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id, filename, file_type, file_size,
                chunk_count, int(has_tables), datetime.now().isoformat(),
            ),
        )
        conn.commit()


def get_document_session(doc_id: str) -> Optional[Dict]:
    """Get a document session by doc_id."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM document_sessions WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_document_sessions() -> List[Dict]:
    """Get all uploaded documents, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM document_sessions ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_document_session(doc_id: str) -> bool:
    """Delete a document session record."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM document_sessions WHERE doc_id = ?", (doc_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
