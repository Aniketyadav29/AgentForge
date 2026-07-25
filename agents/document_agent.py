"""
AgentForge — Document Analysis Specialist Agent
A standalone agent that answers questions grounded in uploaded documents
and performs precise mathematical computations on tabular data.
"""

import json
from typing import Optional
from crewai import Agent, Task, Crew, Process
from crewai.tools import BaseTool
from pydantic import Field

from agents.agents import _get_llm
from agents.vector_store import query_document
from agents.math_tools import MathComputationTool, get_schema_summary, execute_math


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
        max_iter=2,
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
            f"1. Use the Document Vector Search tool to find relevant context "
            f"   (doc_id='{doc_id}', query=the question or related keywords).\n"
            f"2. Base your answer STRICTLY on the retrieved context.\n"
            f"3. If the answer is not in the document, respond: "
            f"   'This information is not available in the uploaded document.'\n"
            f"4. Cite which part of the document your answer comes from.\n"
            f"5. Be concise and precise."
            f"{math_instruction}"
        ),
        expected_output=(
            "A precise, grounded answer to the question with:\n"
            "- Direct answer in 1-3 sentences\n"
            "- Source reference (which section/page/chunk the answer came from)\n"
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
        "computation_steps": None,   # populated by math tool output if present
    }
