# ⚡ AgentForge — Autonomous Multi-Agent AI Research Assistant

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI Framework" />
  <img src="https://img.shields.io/badge/CrewAI-Orchestration-FF6B6B?style=for-the-badge&logo=ai&logoColor=white" alt="CrewAI Orchestration" />
  <img src="https://img.shields.io/badge/Groq-Llama%203.3%2070B-f05138?style=for-the-badge&logo=groq&logoColor=white" alt="Groq Llama 3.3" />
  <img src="https://img.shields.io/badge/Google%20Gemini-2.0%20Flash-4285F4?style=for-the-badge&logo=googlegemini&logoColor=white" alt="Google Gemini" />
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License" />
</p>

<p align="center">
  An enterprise-grade, autonomous <b>Multi-Agent AI System</b> where specialized AI agents collaborate in a sequential pipeline to research any topic, perform live web search & scraping, analyze complex data, and produce executive-ready markdown reports — streamed live to a modern dashboard via Server-Sent Events (SSE).
</p>

---

## 🌟 Key Features

- 🤖 **4 Specialized Autonomous AI Agents**:
  - **Research Strategist**: Deconstructs complex queries into actionable research plans.
  - **Web Research Specialist**: Conducts live web searches and extracts data using Serper & Scrape tools.
  - **Data Analyst**: Fact-checks findings, builds side-by-side comparison tables, and structures data.
  - **Report Writer**: Synthesizes analysis into a 6-part executive markdown report.
- ⚡ **Multi-Tier Model Fallback & Resiliency**: Automatic failover between **Groq (Llama 3.3 70B, Llama 3.1 8B, Gemma 2 9B)** and **Google Gemini 2.0 Flash** to prevent 429 rate limits or daily quota shutdowns.
- 📡 **Real-Time Agent Activity Streaming**: Server-Sent Events (SSE) stream every step, tool invocation, and status update live to the web frontend.
- 🎯 **Multi-Depth Execution Modes**:
  - **Quick**: 2 tasks (`~1 min` • 3 aspects)
  - **Detailed**: 3 tasks (`~2 min` • 5-7 aspects)
  - **Deep Dive**: 4 tasks (`~4 min` • 8-10 aspects)
- 💾 **Persistent SQLite Research History**: Store, view, search, copy, or download previous research reports.
- 🎨 **Glassmorphism Dark-Mode Dashboard**: Sleek, responsive web UI built with modern HTML5, Vanilla CSS, and JavaScript.

---

## 🏗️ System Architecture

```
                                  ┌─────────────────────────────┐
                                  │      User Research Query    │
                                  └──────────────┬──────────────┘
                                                 │
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                CrewAI Multi-Agent Pipeline                               │
│                                                                                         │
│  ┌──────────────────────┐    ┌──────────────────────┐    ┌───────────────────────────┐  │
│  │  Research Strategist │───►│ Web Research Specialist│──►│        Data Analyst       │  │
│  │  (Plans Methodology) │    │  (Search & Scrape)   │    │ (Categorizes & Fact-Checks│  │
│  └──────────────────────┘    └──────────────────────┘    └─────────────┬─────────────┘  │
│                                                                        │                │
│                                                                        ▼                │
│                                                              ┌───────────────────┐      │
│                                                              │   Report Writer   │      │
│                                                              │  (Synthesizes)    │      │
│                                                              └─────────┬─────────┘      │
└────────────────────────────────────────────────────────────────────────┼────────────────┘
                                                                         │
                                                                         ▼
                                                       ┌──────────────────────────────────┐
                                                       │ Executive Markdown Research Guide│
                                                       └──────────────────────────────────┘
```

---

## 🤖 The Multi-Agent Crew

| Agent | Icon | Role & Description | Capabilities & Tools |
| :--- | :---: | :--- | :--- |
| **Research Strategist** | 🔍 | Formulates the multi-vector research plan and key questions to investigate. | High-level reasoning, query decomposition. |
| **Web Research Specialist** | 🌐 | Conducts targeted Google searches, scrapes web pages, and extracts facts. | `SerperDevTool`, `ScrapeWebsiteTool`. |
| **Data Analyst** | 📊 | Fact-checks findings, structures data, and builds comparison matrices. | Markdown table synthesis, fact-checking. |
| **Report Writer** | 📝 | Compiles all findings into a structured 6-section executive report. | Executive synthesis, report formatting. |

---

## 🛠️ Technology Stack

- **Orchestration**: [CrewAI](https://crewai.com) (Multi-agent process automation)
- **LLM Infrastructure**: [Groq API](https://groq.com) (`Llama 3.3 70B Versatile`, `Llama 3.1 8B Instant`, `Gemma 2 9B`) & [Google Gemini 2.0 Flash](https://ai.google.dev)
- **Backend Framework**: [FastAPI](https://fastapi.tiangolo.com) (Async Python web server)
- **Real-Time Streaming**: Server-Sent Events (SSE via `sse-starlette`)
- **Database**: SQLite3 (Research history persistence)
- **Vector Search / RAG**: ChromaDB & Scikit-Learn Fast Hashing Vectorizer
- **Frontend**: Vanilla HTML5, CSS3 Glassmorphic Design System, ES6 JavaScript

---

## 🚀 Quick Start & Installation

### 1. Prerequisites
- **Python 3.10** or higher
- **Groq API Key**: Get a free key at [console.groq.com](https://console.groq.com)
- **Serper API Key**: Get a free search key (2,500 queries) at [serper.dev](https://serper.dev)
- **Gemini API Key** *(Optional)*: Get a free key at [aistudio.google.com](https://aistudio.google.com)

### 2. Clone the Repository
```bash
git clone https://github.com/Aniketyadav29/AgentForge.git
cd AgentForge
```

### 3. Create & Activate Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables
Create or update the `.env` file in the root directory:
```env
GROQ_API_KEY=your_groq_api_key_here
MODEL_NAME=groq/llama-3.3-70b-versatile
GEMINI_API_KEY=your_gemini_api_key_here
SERPER_API_KEY=your_serper_api_key_here
ANONYMIZED_TELEMETRY=False
```

### 6. Launch the Server
```bash
python main.py
```

### 7. Access Dashboard
Open your web browser and navigate to:
```
http://localhost:8000
```

---

## 📡 API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/research` | Initialize a new multi-agent research session |
| `GET` | `/api/research/{session_id}/stream` | SSE stream for real-time agent thought logs |
| `GET` | `/api/research/{session_id}/result` | Fetch completed research report |
| `GET` | `/api/history` | List all historical research sessions |
| `GET` | `/api/history/{session_id}` | Fetch a specific past report |
| `DELETE` | `/api/history/{session_id}` | Delete a research session |
| `GET` | `/health` | API health check endpoint |

---

## 📁 Repository Structure

```
AgentForge/
├── .env                    # API keys & configuration
├── .gitignore              # Protected secret exclusions
├── README.md               # Project documentation
├── requirements.txt        # Python package dependencies
├── main.py                 # FastAPI server & route handlers
├── agents/
│   ├── agents.py           # CrewAI agent definitions & model fallbacks
│   ├── crew.py             # Session orchestration & SSE event engine
│   ├── tasks.py            # Sequential task pipeline & intent prompts
│   ├── tools.py            # Custom search & website scraping tools
│   ├── vector_store.py     # ChromaDB vector store RAG manager
│   └── document_agent.py   # Document analysis specialist
├── database/
│   └── db.py               # SQLite database CRUD operations
├── models/
│   └── schemas.py          # Pydantic request/response schemas
└── static/
    ├── index.html           # Dark-mode dashboard web interface
    ├── css/styles.css       # Premium CSS design system
    └── js/
        ├── app.js           # Frontend application controller
        ├── agents-panel.js  # Live agent activity renderer
        └── report-viewer.js # Markdown report viewer & exporter
```

---

## 📄 License

This project is licensed under the **MIT License** — feel free to use it for personal, educational, or commercial projects.

---

<p align="center">
  <b>Built with ❤️ by Aniket Yadav</b>
</p>
