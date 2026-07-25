"""
AgentForge — Universal File Parser
Handles PDF, CSV, Excel, DOCX, and TXT files.
Returns structured text + DataFrames for downstream processing.
"""

import io
import os
from pathlib import Path
from typing import Optional
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_import(module: str):
    """Try to import a module and return None on failure."""
    import importlib
    try:
        return importlib.import_module(module)
    except ImportError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Individual parsers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_pdf(file_bytes: bytes) -> dict:
    """Parse PDF using pdfplumber for accurate text + table extraction."""
    pdfplumber = _safe_import("pdfplumber")
    if not pdfplumber:
        raise ImportError("pdfplumber not installed. Run: pip install pdfplumber")

    text_pages = []
    tables: list[pd.DataFrame] = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            # Extract plain text
            page_text = page.extract_text() or ""
            text_pages.append(f"[Page {page_num}]\n{page_text}")

            # Extract tables as DataFrames
            for table in page.extract_tables():
                if table and len(table) > 1:
                    try:
                        df = pd.DataFrame(table[1:], columns=table[0])
                        df = df.dropna(how="all")
                        tables.append(df)
                    except Exception:
                        pass

    return {
        "text": "\n\n".join(text_pages),
        "tables": tables,
        "page_count": len(pdf.pages) if hasattr(pdf, "pages") else None,
    }


def _parse_csv(file_bytes: bytes) -> dict:
    """Parse CSV using pandas."""
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
    except Exception:
        df = pd.read_csv(io.BytesIO(file_bytes), encoding="latin-1")

    text = f"CSV Data ({len(df)} rows × {len(df.columns)} columns)\n\n"
    text += f"Columns: {', '.join(str(c) for c in df.columns)}\n\n"
    text += "Data Preview (first 20 rows):\n"
    text += df.head(20).to_string(index=False)
    text += "\n\nStatistical Summary:\n"
    text += df.describe(include="all").to_string()

    return {"text": text, "tables": [df], "row_count": len(df)}


def _parse_excel(file_bytes: bytes) -> dict:
    """Parse Excel (.xlsx / .xls) — all sheets."""
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    all_text = []
    tables = []

    for sheet_name in xl.sheet_names:
        df = xl.parse(sheet_name)
        tables.append(df)
        text = f"Sheet: {sheet_name} ({len(df)} rows × {len(df.columns)} cols)\n"
        text += f"Columns: {', '.join(str(c) for c in df.columns)}\n"
        text += df.head(20).to_string(index=False)
        all_text.append(text)

    return {
        "text": "\n\n".join(all_text),
        "tables": tables,
        "sheet_count": len(xl.sheet_names),
    }


def _parse_docx(file_bytes: bytes) -> dict:
    """Parse DOCX using python-docx."""
    docx = _safe_import("docx")
    if not docx:
        raise ImportError("python-docx not installed. Run: pip install python-docx")

    from docx import Document
    doc = Document(io.BytesIO(file_bytes))

    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    tables = []
    for tbl in doc.tables:
        rows = [[cell.text for cell in row.cells] for row in tbl.rows]
        if rows:
            try:
                df = pd.DataFrame(rows[1:], columns=rows[0])
                tables.append(df)
            except Exception:
                pass

    return {
        "text": "\n".join(paragraphs),
        "tables": tables,
        "paragraph_count": len(paragraphs),
    }


def _parse_txt(file_bytes: bytes) -> dict:
    """Parse plain text files."""
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")
    return {"text": text, "tables": []}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".xls", ".docx", ".txt"}


def parse_file(file_bytes: bytes, filename: str) -> dict:
    """
    Parse an uploaded file and return structured data.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        filename:   Original filename (used to detect format).

    Returns:
        {
            "text":      Full extracted text (str),
            "tables":    List of pandas DataFrames extracted from the file,
            "metadata":  Dict with file-specific metadata,
            "file_type": Detected file type string,
        }

    Raises:
        ValueError if the file extension is not supported.
    """
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    parsers = {
        ".pdf":  _parse_pdf,
        ".csv":  _parse_csv,
        ".xlsx": _parse_excel,
        ".xls":  _parse_excel,
        ".docx": _parse_docx,
        ".txt":  _parse_txt,
    }

    result = parsers[ext](file_bytes)
    result["file_type"] = ext.lstrip(".")
    result["metadata"] = {
        "filename": filename,
        "file_type": ext.lstrip("."),
        "file_size_bytes": len(file_bytes),
        "table_count": len(result.get("tables", [])),
        "has_tables": len(result.get("tables", [])) > 0,
    }
    return result
