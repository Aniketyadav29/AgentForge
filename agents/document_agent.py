"""
AgentForge — Document Analysis Specialist Agent
A standalone agent that answers questions grounded in uploaded documents
and performs precise mathematical computations on tabular data.
"""

import json
from typing import Optional
from pydantic import Field

from agents.vector_store import query_document
from agents.math_tools import MathComputationTool, get_schema_summary, execute_math, pop_computation_steps

try:
    from crewai import Agent, Task, Crew, Process
    from crewai.tools import BaseTool
    from agents.agents import _get_llm
    CREWAI_AVAILABLE = True
except Exception:
    Agent = Task = Crew = Process = None
    CREWAI_AVAILABLE = False

    class BaseTool:
        """Small fallback so deterministic document reports work without CrewAI."""

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)


# ─────────────────────────────────────────────────────────────────────────────
# Vector Search Tool
# ─────────────────────────────────────────────────────────────────────────────

class VectorSearchTool(BaseTool):
    """Semantic search across the uploaded document's vector store."""

    name: str = "document_vector_search"
    description: str = (
        "Search the uploaded document for relevant context to answer a question. "
        "Input must be a JSON string with 'doc_id' (str) and 'query' (str). "
        "Returns the top matching text chunks from the document."
    )
    doc_id: str = Field(default="", description="Document ID to search within")

    def _run(self, input_str: str) -> str:
        import re
        try:
            # First try standard JSON parsing
            data   = json.loads(input_str)
            doc_id = data.get("doc_id", self.doc_id)
            query  = data.get("query", "")
        except (json.JSONDecodeError, AttributeError):
            # Fallback: extract JSON from malformed function-call strings
            # e.g. '<function=document_vector_search [{...}](...)'  
            json_match = re.search(r'\[\s*(\{.*?\})\s*\]', str(input_str), re.DOTALL)
            if json_match:
                try:
                    data   = json.loads(json_match.group(1))
                    doc_id = data.get("doc_id", self.doc_id)
                    query  = data.get("query", "")
                except Exception:
                    doc_id = self.doc_id
                    query  = input_str.strip()
            else:
                doc_id = self.doc_id
                query  = input_str.strip()

        if not query:
            return "Error: No search query provided."

        results = query_document(doc_id, query, top_k=5)
        if not results:
            return "No relevant content found in the document for this query."

        chunks = []
        for i, r in enumerate(results, 1):
            score = r.get("score", 0)
            text  = r.get("text", "")
            chunks.append(f"[Chunk {i} | Relevance: {score:.2f}]\n{text}")

        return "\n\n---\n\n".join(chunks)


# ─────────────────────────────────────────────────────────────────────────────
# Document Analysis Agent factory
# ─────────────────────────────────────────────────────────────────────────────

def create_document_agent(doc_id: str, filename: str, has_tables: bool) -> Agent:
    """
    Create a Document Analysis Specialist agent configured for a specific document.

    Args:
        doc_id:     The uploaded document's ID.
        filename:   Original filename (for context).
        has_tables: Whether the document contains tabular data.
    """
    if not CREWAI_AVAILABLE:
        raise RuntimeError("CrewAI is not installed; using deterministic document fallback.")

    tools = [VectorSearchTool(doc_id=doc_id)]
    if has_tables:
        tools.append(MathComputationTool(doc_id=doc_id))

    math_note = (
        " You also have a Math Computation Tool — use it for ANY numerical "
        "question (sums, averages, counts, statistical analysis). "
        "NEVER guess math — always compute it."
        if has_tables else ""
    )

    llm = _get_llm()
    return Agent(
        role="Document Analysis Specialist",
        goal=(
            f"Accurately answer user questions about the uploaded document '{filename}' "
            f"using ONLY the information contained within it. "
            f"Ground every answer in specific text or data from the document."
            f"{math_note}"
        ),
        backstory=(
            "You are a world-class document analyst and data scientist. "
            "You have studied thousands of research papers, financial reports, and datasets. "
            "Your superpower is extracting precise insights from documents and performing "
            "exact mathematical computations — never estimating, always computing. "
            "You are known for being honest: if something isn't in the document, you say so."
        ),
        tools=tools,
        llm=llm,
        function_calling_llm=llm,
        verbose=True,
        max_iter=3,
        allow_delegation=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Query runner
# ─────────────────────────────────────────────────────────────────────────────

def answer_document_question(
    doc_id: str,
    filename: str,
    has_tables: bool,
    question: str,
    schema_summary: Optional[str] = None,
) -> dict:
    """
    Run the Document Analysis Agent to answer a question about a document.

    Returns:
        { "answer": str, "sources": list, "computation_steps": str|None }
    """
    if not CREWAI_AVAILABLE:
        sources = query_document(doc_id, question, top_k=5)
        if sources:
            context = "\n\n".join(r["text"] for r in sources)
            # Try to synthesize using Gemini or Groq LLM if available
            import os, urllib.request, json
            gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            groq_key = os.environ.get("GROQ_API_KEY")
            answer_text = ""

            if gemini_key and gemini_key != "your_gemini_api_key_here":
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
                    prompt = (
                        f"Based on the following document context, answer the user question COMPREHENSIVELY and IN DETAIL.\n\n"
                        f"Document Context:\n{context[:6000]}\n\n"
                        f"Question: {question}\n\n"
                        f"Instructions: Provide a thorough, detailed answer. Include all relevant information from the document. "
                        f"If there are specific facts, numbers, dates, or names, include them. "
                        f"Structure your answer clearly with context, explanation, and examples where relevant."
                    )
                    req = urllib.request.Request(
                        url,
                        data=json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        res_data = json.loads(resp.read().decode("utf-8"))
                        answer_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                except Exception:
                    pass

            if not answer_text:
                answer_text = (
                    f"Based on the uploaded document '{filename}', here is the most relevant extracted context:\n\n"
                    f"{context[:2200]}"
                )
        else:
            answer_text = "This information is not available in the uploaded document."
        return {
            "answer": answer_text,
            "sources": [
                {"chunk": r["text"][:200] + ("..." if len(r["text"]) > 200 else ""), "score": r["score"]}
                for r in sources[:3]
            ],
            "computation_steps": pop_computation_steps(doc_id),
        }

    agent = create_document_agent(doc_id, filename, has_tables)

    # Build task description
    math_instruction = ""
    if has_tables and schema_summary:
        math_instruction = (
            f"\n\nAvailable tabular data:\n{schema_summary}\n\n"
            f"For any numerical questions, use the Math Computation Tool with "
            f"doc_id='{doc_id}' and a valid pandas expression."
        )

    task = Task(
        description=(
            f"Answer the following question about the document '{filename}':\n\n"
            f"**Question:** {question}\n\n"
            f"Instructions:\n"
            f"1. Use the Document Vector Search tool MULTIPLE TIMES to find all relevant context "
            f"   (doc_id='{doc_id}', query=the question and related keywords).\n"
            f"2. Search with at least 2-3 different query phrasings to capture all relevant information.\n"
            f"3. Base your answer STRICTLY on the retrieved context.\n"
            f"4. Provide a COMPREHENSIVE, DETAILED answer — do NOT summarize superficially.\n"
            f"5. Include specific facts, numbers, names, dates, and quotes from the document.\n"
            f"6. If the answer is not in the document, respond: "
            f"   'This information is not available in the uploaded document.'\n"
            f"7. Cite which section/page/chunk your answer comes from."
            f"{math_instruction}"
        ),
        expected_output=(
            "A COMPREHENSIVE, DETAILED answer to the question with:\n"
            "- Full detailed answer with all relevant facts, numbers, names, and context\n"
            "- Multiple paragraphs covering all aspects of the question\n"
            "- Source references (section/page/chunk the answer came from)\n"
            "- For math questions: the computed result with step-by-step explanation"
        ),
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )

    try:
        result = crew.kickoff()
        answer_text = result.raw if hasattr(result, "raw") else str(result)
    except Exception as crew_err:
        err_str = str(crew_err)
        # If the LLM failed to call the tool properly (common with some Groq/Llama models),
        # fall back to a direct vector search + simple answer synthesis.
        if "tool_use_failed" in err_str or "400" in err_str or "failed_generation" in err_str:
            from agents.vector_store import query_document as _qd
            fallback_results = _qd(doc_id, question, top_k=5)
            if fallback_results:
                context = "\n\n".join(r["text"] for r in fallback_results)
                answer_text = (
                    f"Based on the document '{filename}':\n\n{context[:2000]}"
                )
            else:
                answer_text = "This information is not available in the uploaded document."
        else:
            raise

    # Retrieve source chunks used (re-query for display)
    sources = query_document(doc_id, question, top_k=3)
    source_texts = [
        {"chunk": r["text"][:200] + "...", "score": r["score"]}
        for r in sources
    ]

    return {
        "answer": answer_text,
        "sources": source_texts,
        "computation_steps": pop_computation_steps(doc_id),
    }


def build_document_report(
    doc_id: str,
    filename: str,
    file_type: str,
    has_tables: bool,
    extracted_text: str,
    schema_summary: Optional[str] = None,
) -> dict:
    """Build a complete, deterministic report from extracted document content."""
    import re

    clean_text = re.sub(r"\s+", " ", extracted_text or "").strip()
    words = clean_text.split()
    preview = clean_text[:2200] if clean_text else "No readable text was extracted."
    sections = []

    if clean_text:
        sentences = re.split(r"(?<=[.!?])\s+", clean_text)
        sections = [s.strip() for s in sentences if len(s.split()) >= 8][:8]

    sources = query_document(doc_id, "executive summary key findings metrics conclusions", top_k=5)
    source_texts = [
        {"chunk": r["text"][:240] + ("..." if len(r["text"]) > 240 else ""), "score": r["score"]}
        for r in sources
    ]

    report_parts = [
        f"# Complete Analysis Report: {filename}",
        "## Executive Summary",
        (
            f"The uploaded {file_type.upper()} file was parsed and indexed successfully. "
            f"It contains approximately {len(words):,} extracted words and "
            f"{'includes tabular data that can be queried with exact calculations' if has_tables else 'does not expose structured tables for math operations'}."
        ),
        "## Content Snapshot",
        preview,
        "## Key Findings",
    ]

    if sections:
        report_parts.extend(f"- {sentence}" for sentence in sections[:6])
    else:
        report_parts.append("- No substantive text was extracted. For images, install OCR tooling or use a vision-capable model for deeper visual understanding.")

    report_parts.append("## Data And Structure")
    if schema_summary:
        report_parts.append(schema_summary)
    elif has_tables:
        report_parts.append(get_schema_summary(doc_id))
    else:
        report_parts.append("No table schema was detected in this file.")

    report_parts.extend([
        "## Suggested Follow-Up Questions",
        "- Summarize the strongest evidence and the weakest assumptions.",
        "- Extract all dates, entities, dollar amounts, and percentages.",
        "- Identify risks, anomalies, contradictions, and missing information.",
        "- Convert this into an executive action plan.",
        "## Notes",
        "This report is generated from locally extracted content. If an image has no OCR text, the report is limited to image metadata unless a vision model/OCR engine is configured.",
    ])

    return {
        "report": "\n\n".join(report_parts),
        "sources": source_texts,
    }
