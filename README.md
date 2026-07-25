# ⚡ AgentForge — Multi-Agent AI Research Assistant

An industry-grade **Multi-Agent AI system** where 4 specialized AI agents collaborate to research any topic, scrape live web data, analyze findings, and generate comprehensive reports — all visible in real-time through a stunning web dashboard.

> Built with **CrewAI** • **Google Gemini 2.0 Flash** • **FastAPI** • **Server-Sent Events**

---

## 🏗️ Architecture

```
User Query → Research Strategist → Web Scraper → Data Analyst → Report Writer → Final Report
                  (Plans)           (Scrapes)     (Analyzes)      (Writes)
```

### The 4 Agents

| Agent | Role | Tools |
|-------|------|-------|
| 🔍 **Research Strategist** | Plans the research methodology and identifies key questions | Reasoning only |
| 🌐 **Web Research Specialist** | Searches the web and scrapes relevant content | SerperDevTool, ScrapeWebsiteTool |
| 📊 **Data Analyst** | Structures data, identifies trends, performs analysis | Reasoning only |
| 📝 **Report Writer** | Synthesizes everything into a polished research report | Reasoning only |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- [Gemini API Key](https://aistudio.google.com/apikey) (free)
- [Serper API Key](https://serper.dev/) (free 2,500 searches)

### Installation

```bash
# 1. Navigate to project directory
cd "Multi agentic AI"

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up API keys in .env
# Edit .env and add your actual API keys

# 5. Run the server
python main.py
```

### Open the Dashboard
Navigate to **http://127.0.0.1:8000** in your browser.

---

## 🛠️ Tech Stack

| Technology | Purpose |
|-----------|---------|
| **CrewAI** | Multi-agent orchestration framework |
| **Google Gemini 2.0 Flash** | LLM powering all agents (via LiteLLM) |
| **FastAPI** | High-performance async API server |
| **SSE (Server-Sent Events)** | Real-time agent activity streaming |
| **SQLite** | Research history persistence |
| **Vanilla JS** | Premium dark-mode dashboard (no framework needed) |

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/research` | Start a new research session |
| `GET` | `/api/research/{id}/stream` | SSE stream of agent activity |
| `GET` | `/api/research/{id}/result` | Get the final research report |
| `GET` | `/api/history` | List all past research sessions |
| `GET` | `/api/history/{id}` | Get a specific past report |
| `DELETE` | `/api/history/{id}` | Delete a research session |
| `GET` | `/health` | Health check |

---

## 📁 Project Structure

```
Multi agentic AI/
├── .env                    # API keys
├── requirements.txt        # Dependencies
├── main.py                 # FastAPI server
├── agents/
│   ├── agents.py           # 4 specialized agent definitions
│   ├── tasks.py            # Sequential task definitions
│   ├── tools.py            # Web search & scraping tools
│   └── crew.py             # Crew orchestration engine
├── models/
│   └── schemas.py          # Pydantic data models
├── database/
│   └── db.py               # SQLite operations
└── static/
    ├── index.html           # Dashboard page
    ├── css/styles.css       # Dark-mode design system
    └── js/
        ├── app.js           # Main controller
        ├── agents-panel.js  # Agent activity visualization
        └── report-viewer.js # Report rendering
```

---

## 🧠 How It Works

1. **User submits a research topic** via the web dashboard
2. **Research Strategist** analyzes the topic and creates a structured research plan
3. **Web Research Specialist** executes web searches and scrapes relevant content
4. **Data Analyst** structures and analyzes the gathered data
5. **Report Writer** synthesizes everything into a comprehensive markdown report
6. **Real-time updates** stream via SSE to the dashboard as agents work
7. **Final report** is rendered in the dashboard and saved to history

---

## 📝 License

This project is for educational and portfolio purposes.
