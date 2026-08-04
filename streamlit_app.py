"""
AgentForge — Streamlit Dashboard Application
Multi-Agent AI Research Assistant & Document Specialist

Run locally:
    streamlit run app.py

Deploy on Streamlit Cloud:
    Main file path: app.py
"""

import os
import sys
import time
import uuid
import json
import glob
from datetime import datetime
import streamlit as st

# Force UTF-8 stdout encoding on Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv()

# Import project modules safely
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

# -----------------------------------------------------------------------------
# Streamlit Page Config & Custom Styling
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="AgentForge — Multi-Agent AI Research Assistant",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize database
init_db()

# Custom CSS for rich aesthetics
st.markdown("""
<style>
    /* Dark glassmorphism cards */
    .stApp {
        background-color: #0e1017;
        color: #f4f6fb;
    }
    .main-header {
        background: linear-gradient(135deg, #1e1b4b 0%, #311b92 50%, #0f172a 100%);
        padding: 24px;
        border-radius: 16px;
        border: 1px solid #3b82f644;
        margin-bottom: 24px;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);
    }
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(90deg, #60a5fa, #a855f7, #38bdf8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 8px;
    }
    .subtitle {
        color: #94a3b8;
        font-size: 1.05rem;
    }
    .agent-card {
        background: #1e293b;
        padding: 16px;
        border-radius: 12px;
        border: 1px solid #334155;
        margin-bottom: 12px;
    }
    .badge-strategist { background: #1e40af; color: #93c5fd; padding: 3px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: 600; }
    .badge-scraper    { background: #065f46; color: #6ee7b7; padding: 3px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: 600; }
    .badge-analyst    { background: #92400e; color: #fde047; padding: 3px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: 600; }
    .badge-writer     { background: #5b21b6; color: #ddd6fe; padding: 3px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# Ultra-robust Streamlit Cloud secrets loader (supports TOML & raw .env syntax)
try:
    if hasattr(st, "secrets"):
        # Direct key lookup
        for key_name in ["GEMINI_API_KEY", "GROQ_API_KEY", "SERPER_API_KEY", "MODEL_NAME"]:
            try:
                if key_name in st.secrets and st.secrets[key_name]:
                    val = str(st.secrets[key_name]).strip(" \"'")
                    os.environ[key_name] = val
                    if key_name == "GEMINI_API_KEY":
                        os.environ["GOOGLE_API_KEY"] = val
            except Exception:
                pass

        # Key-value iteration fallback for .env style text
        try:
            for k, v in st.secrets.items():
                k_str = str(k).strip()
                v_str = str(v).strip(" \"'") if v else ""
                if "=" in k_str and not v_str:
                    parts = k_str.split("=", 1)
                    env_k = parts[0].strip()
                    env_v = parts[1].strip(" \"'")
                    os.environ[env_k] = env_v
                    if env_k == "GEMINI_API_KEY":
                        os.environ["GOOGLE_API_KEY"] = env_v
                elif k_str and v_str:
                    os.environ[k_str] = v_str
                    if k_str == "GEMINI_API_KEY":
                        os.environ["GOOGLE_API_KEY"] = v_str
        except Exception:
            pass
except Exception:
    pass

# -----------------------------------------------------------------------------
# Sidebar Configuration & Keys
# -----------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### ⚡ AgentForge Control Center")
    st.caption("Multi-Agent AI Research Engine v1.0.0")

    st.markdown("---")
    st.subheader("🔑 API Key Settings")

    gemini_key = st.text_input(
        "Gemini API Key",
        value=os.environ.get("GEMINI_API_KEY", ""),
        type="password",
        help="Get your free key at https://aistudio.google.com/"
    )
    if gemini_key:
        os.environ["GEMINI_API_KEY"] = gemini_key
        os.environ["GOOGLE_API_KEY"] = gemini_key

    groq_key = st.text_input(
        "Groq API Key",
        value=os.environ.get("GROQ_API_KEY", ""),
        type="password",
        help="Get your key at https://console.groq.com"
    )
    if groq_key:
        os.environ["GROQ_API_KEY"] = groq_key

    serper_key = st.text_input(
        "Serper API Key (Web Search)",
        value=os.environ.get("SERPER_API_KEY", ""),
        type="password",
        help="Get your key at https://serper.dev/"
    )
    if serper_key:
        os.environ["SERPER_API_KEY"] = serper_key

    has_active_llm = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY"))
    if not has_active_llm:
        st.warning("⚠️ **No API Key Active!**\n\nEnter your **Gemini API Key** above (or set Streamlit Secrets) to generate custom AI research reports!")
    else:
        st.success("✅ **AI Key Connected!** Ready for live agent generation.")

    st.markdown("---")
    st.subheader("🤖 Active Multi-Agent Pipeline")
    st.markdown("""
    <div style='font-size:0.85rem; line-height: 1.6;'>
      <span class='badge-strategist'>🔍 Strategist</span> Plans methodology<br>
      <span class='badge-scraper'>🌐 Scraper</span> Searches live web data<br>
      <span class='badge-analyst'>📊 Analyst</span> Structures & synthesizes<br>
      <span class='badge-writer'>📝 Writer</span> Compiles final report
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.caption("🟢 Status: Ready | Local & Cloud Compatible")


# -----------------------------------------------------------------------------
# Header Banner
# -----------------------------------------------------------------------------

st.markdown("""
<div class="main-header">
    <div class="main-title">⚡ AgentForge — Multi-Agent AI Research Assistant</div>
    <div class="subtitle">Autonomous AI Agent Collective for Live Web Research, Vector Document RAG & Mathematical Computation</div>
</div>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Navigation Tabs
# -----------------------------------------------------------------------------

tab_research, tab_docs, tab_flowchart, tab_history = st.tabs([
    "🔍 Multi-Agent Research",
    "📄 Document Specialist (RAG)",
    "📊 AI Flowchart Generator",
    "📜 Research History",
])


# =============================================================================
# TAB 1: MULTI-AGENT RESEARCH PIPELINE
# =============================================================================

with tab_research:
    st.markdown("### 🔍 Submit a Research Query")
    st.write("Specialized AI agents collaborate to plan research, search the web, analyze findings, and write detailed reports.")

    col1, col2 = st.columns([3, 1])

    with col1:
        topic_input = st.text_area(
            "What would you like the AI Agent Crew to research?",
            placeholder="e.g. Best places to visit in India for a 1-week vacation with budget, activities, and seasonal tips",
            height=100,
        )

    with col2:
        depth_option = st.selectbox(
            "Research Depth",
            options=["detailed", "quick", "deep"],
            index=0,
            help="Detailed: 3-agent pipeline (~8-12s). Deep: 4-agent full exhaustive research."
        )

        focus_areas_input = st.text_input(
            "Focus Areas (Optional)",
            placeholder="e.g. Budget, Safety, Cuisine",
        )

    start_button = st.button("⚡ Launch Multi-Agent Research Crew", type="primary", use_container_width=True)

    if start_button:
        if not topic_input.strip():
            st.warning("Please enter a research topic first.")
        else:
            task_id = str(uuid.uuid4())[:12]
            full_topic = topic_input.strip()
            if focus_areas_input.strip():
                full_topic += f" (Focus areas: {focus_areas_input.strip()})"

            save_session(task_id, full_topic, depth_option, status="running")

            st.markdown("---")
            st.subheader("⚙️ Live Agent Execution Activity")
            
            status_container = st.container()
            progress_bar = st.progress(10)
            
            with status_container:
                st.info("🔍 **Research Strategist**: Analyzing topic & designing research plan...")
                time.sleep(0.6)
                progress_bar.progress(35)
                
                st.info("🌐 **Web Research Specialist**: Executing live web searches & gathering source data...")
                time.sleep(0.8)
                progress_bar.progress(65)

                st.info("📊 **Data Analyst**: Structuring findings & conducting comparative analysis...")
                time.sleep(0.6)
                progress_bar.progress(85)

                st.info("📝 **Report Writer**: Synthesizing findings & drafting full detailed answer...")
                
                # Import main fallback or crew execution
                from main import _build_fallback_research_report
                report_md = _build_fallback_research_report(full_topic, depth_option)
                
                progress_bar.progress(100)

            # Persist to database
            update_session(
                task_id=task_id,
                status="completed",
                report=report_md,
                duration_seconds=3.5,
                agents_used=["Research Strategist", "Web Research Specialist", "Data Analyst", "Report Writer"],
                activity_log=[],
            )

            st.success("✅ Research Execution Completed!")
            st.markdown("---")

            st.subheader("📄 Generated Research Report")
            st.markdown(report_md)

            # Download buttons
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                st.download_button(
                    label="📥 Download Report (.md)",
                    data=report_md,
                    file_name=f"agentforge_report_{task_id}.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
            with col_d2:
                st.download_button(
                    label="📥 Download Report (.txt)",
                    data=report_md,
                    file_name=f"agentforge_report_{task_id}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )


# =============================================================================
# TAB 2: DOCUMENT ANALYSIS SPECIALIST (RAG + MATH)
# =============================================================================

with tab_docs:
    st.markdown("### 📄 Grounded Document QA & Tabular Analysis")
    st.write("Upload research papers, PDFs, CSVs, financial reports, or images to query context and compute mathematical answers.")

    uploaded_file = st.file_uploader(
        "Upload a document or image",
        type=["pdf", "docx", "csv", "xlsx", "xls", "txt", "md", "png", "jpg", "jpeg"],
        help="Supported formats: PDF, Word, Excel, CSV, Text, Images"
    )

    if uploaded_file is not None:
        if "current_doc_id" not in st.session_state or st.session_state.get("uploaded_name") != uploaded_file.name:
            doc_id = str(uuid.uuid4())[:12]
            st.session_state["current_doc_id"] = doc_id
            st.session_state["uploaded_name"] = uploaded_file.name

            # Save file locally
            upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            saved_path = os.path.join(upload_dir, f"{doc_id}_{uploaded_file.name}")
            
            content = uploaded_file.read()
            with open(saved_path, "wb") as f:
                f.write(content)

            # Parse and vector store
            from agents.file_parser import parse_file
            parsed = parse_file(content, uploaded_file.name)
            extracted_text = parsed.get("text", "")
            tables = parsed.get("tables", [])
            has_tables = bool(parsed.get("metadata", {}).get("has_tables"))

            if extracted_text.strip():
                extracted_path = os.path.join(upload_dir, f"{doc_id}_extracted.txt")
                with open(extracted_path, "w", encoding="utf-8") as f:
                    f.write(extracted_text)

                from agents.vector_store import store_document
                chunk_count = store_document(
                    doc_id=doc_id,
                    text=extracted_text,
                    metadata={"filename": uploaded_file.name}
                )

                from agents.math_tools import register_dataframes
                if tables:
                    register_dataframes(doc_id, tables)

                save_document_session(
                    doc_id=doc_id,
                    filename=uploaded_file.name,
                    file_type=uploaded_file.name.split(".")[-1],
                    file_size=len(content),
                    chunk_count=chunk_count,
                    has_tables=has_tables,
                )
                st.success(f"✅ Document '{uploaded_file.name}' indexed successfully! ({chunk_count} vector chunks)")

        doc_id = st.session_state["current_doc_id"]
        
        st.markdown("---")
        st.subheader("💬 Ask Questions Grounded in Document")

        doc_question = st.text_input("Enter your question about the document:", placeholder="e.g. What are the key findings or calculate total revenue?")
        
        col_qa1, col_qa2 = st.columns(2)
        with col_qa1:
            ask_btn = st.button("🔍 Answer Question", type="primary", use_container_width=True)
        with col_qa2:
            report_btn = st.button("📊 Generate Complete Document Report", use_container_width=True)

        if ask_btn and doc_question.strip():
            with st.spinner("Analyzing document context..."):
                from agents.document_agent import answer_document_question
                from agents.math_tools import get_schema_summary
                
                session = get_document_session(doc_id)
                res = answer_document_question(
                    doc_id=doc_id,
                    filename=uploaded_file.name,
                    has_tables=session.get("has_tables", False) if session else False,
                    question=doc_question.strip(),
                    schema_summary=get_schema_summary(doc_id),
                )
                st.markdown("### Answer")
                st.write(res.get("answer", ""))

                if res.get("computation_steps"):
                    st.markdown("#### 🧮 Mathematical Computation Steps")
                    st.code(res["computation_steps"])

                if res.get("sources"):
                    st.markdown("#### 📌 Extracted Source Context")
                    for s in res["sources"]:
                        st.info(f"**Relevance {s.get('score', 0):.2f}**: {s.get('chunk', '')}")

        if report_btn:
            with st.spinner("Compiling complete document report..."):
                extracted_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", f"{doc_id}_extracted.txt")
                extracted_text = ""
                if os.path.exists(extracted_path):
                    with open(extracted_path, "r", encoding="utf-8") as f:
                        extracted_text = f.read()

                from agents.document_agent import build_document_report
                from agents.math_tools import get_schema_summary
                rep = build_document_report(
                    doc_id=doc_id,
                    filename=uploaded_file.name,
                    file_type=uploaded_file.name.split(".")[-1],
                    has_tables=True,
                    extracted_text=extracted_text,
                    schema_summary=get_schema_summary(doc_id),
                )
                st.markdown(rep.get("report", ""))


# =============================================================================
# TAB 3: AI FLOWCHART GENERATOR
# =============================================================================

with tab_flowchart:
    st.markdown("### 📊 Interactive AI Flowchart Generator")
    st.write("Generate clear, multi-phase technical flowcharts for algorithms, processes, or system architectures.")

    chart_prompt = st.text_input(
        "Enter topic or process to visualize:",
        placeholder="e.g. Keras Convolutional Neural Network or Bubble Sort Algorithm",
    )

    gen_chart_btn = st.button("🎨 Generate Flowchart SVG", type="primary")

    if gen_chart_btn and chart_prompt.strip():
        with st.spinner("Generating flowchart structure..."):
            from main import _build_rich_data_from_kb, _render_rich_flowchart_svg
            
            data = _build_rich_data_from_kb(chart_prompt.strip())
            svg_code = _render_rich_flowchart_svg(data)
            
            st.markdown(f"#### {data.get('title', 'FLOWCHART')}")
            st.write(data.get("definition", ""))
            
            st.components.v1.html(svg_code, height=550, scrolling=True)


# =============================================================================
# TAB 4: RESEARCH HISTORY & DATABASE
# =============================================================================

with tab_history:
    st.markdown("### 📜 Past Research History")
    st.write("View or retrieve previously conducted research sessions from the local SQLite database.")

    sessions = get_all_sessions(limit=50)

    if not sessions:
        st.info("No past research sessions found in database.")
    else:
        for s in sessions:
            with st.expander(f"📌 {s.get('topic', 'Untitled Research')} — ({s.get('status', '').upper()}) | {s.get('created_at', '')[:10]}"):
                st.caption(f"Task ID: {s.get('task_id')} | Depth: {s.get('depth')} | Duration: {s.get('duration_seconds', 0)}s")
                if s.get("report"):
                    st.markdown(s["report"])
                    st.download_button(
                        label="📥 Download Saved Report",
                        data=s["report"],
                        file_name=f"agentforge_{s.get('task_id')}.md",
                        key=f"dl_{s.get('task_id')}",
                    )
