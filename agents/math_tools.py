"""
AgentForge — Mathematical Computation Tool
A CrewAI BaseTool that safely executes pandas/numpy expressions
on a document's extracted DataFrames.
"""

import ast
import json
import traceback
from typing import Any, Optional, List
import pandas as pd
import numpy as np
from crewai.tools import BaseTool
from pydantic import Field


# ─────────────────────────────────────────────────────────────────────────────
# In-memory DataFrame & Computation registry
# ─────────────────────────────────────────────────────────────────────────────
_dataframe_registry: dict[str, list[pd.DataFrame]] = {}
_latest_computation_steps: dict[str, str] = {}


def register_dataframes(doc_id: str, tables: list[pd.DataFrame]):
    """Register DataFrames from a parsed document for computation."""
    _dataframe_registry[doc_id] = tables


def get_dataframes(doc_id: str) -> list[pd.DataFrame]:
    """Retrieve DataFrames registered for a document."""
    return _dataframe_registry.get(doc_id, [])


def unregister_dataframes(doc_id: str):
    """Remove DataFrames when a document is deleted."""
    _dataframe_registry.pop(doc_id, None)
    _latest_computation_steps.pop(doc_id, None)


def record_computation_steps(doc_id: str, steps: str):
    """Record execution steps for a document math computation."""
    _latest_computation_steps[doc_id] = steps


def pop_computation_steps(doc_id: str) -> Optional[str]:
    """Retrieve and clear latest computation steps for a doc_id."""
    return _latest_computation_steps.pop(doc_id, None)



# ─────────────────────────────────────────────────────────────────────────────
# Safe execution sandbox
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_BUILTINS = {
    "abs", "round", "len", "sum", "min", "max", "sorted", "range",
    "int", "float", "str", "list", "dict", "bool", "print",
}

_BLOCKED_KEYWORDS = [
    "import", "exec", "eval", "open", "os", "__", "subprocess",
    "shutil", "sys", "globals", "locals", "getattr", "setattr",
]


def _is_safe_expression(code: str) -> tuple[bool, str]:
    """Basic safety check — block dangerous constructs."""
    code_lower = code.lower()
    for kw in _BLOCKED_KEYWORDS:
        if kw in code_lower:
            return False, f"Blocked keyword detected: '{kw}'"
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"
    return True, ""


def execute_math(doc_id: str, expression: str) -> dict:
    """
    Safely execute a pandas/numpy expression against the document's DataFrames.

    The expression runs in a restricted sandbox with:
      - df   → first DataFrame (primary table)
      - dfs  → list of all DataFrames
      - pd   → pandas
      - np   → numpy

    Returns:
        { "result": any, "steps": str, "error": str|None }
    """
    tables = get_dataframes(doc_id)

    if not tables:
        return {
            "result": None,
            "steps": "",
            "error": "No tabular data found in this document. "
                     "Math operations require CSV, Excel, or PDF tables.",
        }

    safe, reason = _is_safe_expression(expression)
    if not safe:
        return {"result": None, "steps": "", "error": reason}

    # Build execution context
    df  = tables[0]
    dfs = tables
    context = {
        "df":  df,
        "dfs": dfs,
        "pd":  pd,
        "np":  np,
    }

    steps = []
    steps.append(f"📋 Available DataFrame: {len(df)} rows × {len(df.columns)} columns")
    steps.append(f"📊 Columns: {', '.join(str(c) for c in df.columns)}")
    steps.append(f"🔢 Executing: `{expression}`")

    try:
        result = eval(expression, {"__builtins__": {}}, context)  # noqa: S307

        # Serialize result for JSON-friendliness
        if isinstance(result, pd.DataFrame):
            serialized = result.to_string()
        elif isinstance(result, pd.Series):
            serialized = result.to_string()
        elif isinstance(result, (np.integer, np.floating)):
            serialized = float(result)
        elif isinstance(result, np.ndarray):
            serialized = result.tolist()
        else:
            serialized = result

        steps.append(f"✅ Result: {serialized}")
        return {"result": serialized, "steps": "\n".join(steps), "error": None}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        steps.append(f"❌ Error: {error_msg}")
        return {"result": None, "steps": "\n".join(steps), "error": error_msg}


# ─────────────────────────────────────────────────────────────────────────────
# CrewAI Tool wrappers (used by the Document Agent)
# ─────────────────────────────────────────────────────────────────────────────

class MathComputationTool(BaseTool):
    """Execute pandas/numpy math on the document's tabular data."""

    name: str = "math_computation_tool"
    description: str = (
        "Execute mathematical operations on tabular data extracted from the uploaded document. "
        "Input must be a JSON string with keys: 'doc_id' (str) and 'expression' (str). "
        "The expression runs against 'df' (primary DataFrame) or 'dfs' (list of DataFrames). "
        "Examples: '{\"doc_id\": \"abc\", \"expression\": \"df[\\'Revenue\\'].sum()\"}'"
    )
    doc_id: str = Field(default="", description="Document ID to run math against")

    def _run(self, input_str: str) -> str:
        try:
            data = json.loads(input_str)
            doc_id     = data.get("doc_id", self.doc_id)
            expression = data.get("expression", "")
        except (json.JSONDecodeError, AttributeError):
            # Fallback: treat input as raw expression
            doc_id     = self.doc_id
            expression = input_str.strip()

        if not expression:
            return "Error: No expression provided."

        result = execute_math(doc_id, expression)
        if result.get("steps"):
            record_computation_steps(doc_id, result["steps"])

        if result["error"]:
            return f"Error: {result['error']}\n\nSteps:\n{result['steps']}"
        return f"Result: {result['result']}\n\nSteps:\n{result['steps']}"


def get_schema_summary(doc_id: str) -> str:
    """Get a human-readable summary of available DataFrames for an agent prompt."""
    tables = get_dataframes(doc_id)
    if not tables:
        return "No tabular data available."

    lines = []
    for i, df in enumerate(tables):
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        lines.append(
            f"Table {i} ({len(df)} rows): columns = [{', '.join(str(c) for c in df.columns)}]"
            + (f" | numeric: [{', '.join(str(c) for c in numeric_cols)}]" if numeric_cols else "")
        )
    return "\n".join(lines)
