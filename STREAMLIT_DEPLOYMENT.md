# 🚀 Deploying AgentForge on Streamlit Community Cloud

This guide provides step-by-step instructions to run AgentForge locally with Streamlit or deploy it for **FREE** to [Streamlit Community Cloud](https://streamlit.io/cloud).

---

## 🏃 1. Running Streamlit Locally

### On Windows (1-Click Launchers):
- Double click **`RUN_STREAMLIT.bat`**
- Or run in PowerShell:
  ```powershell
  .\start_streamlit.ps1
  ```

### Manual Command:
```bash
python -m venv .venv
source .venv/bin/activate  # On Linux/macOS
# or .venv\Scripts\activate on Windows

pip install -r requirements-local.txt
streamlit run streamlit_app.py
```

Access the dashboard in your browser at `http://localhost:8501`.

---

## ☁️ 2. Deploying on Streamlit Community Cloud (Free Hosting)

### Step 1: Push Code to GitHub
Ensure your repository contains the following files:
- **`streamlit_app.py`** (Main Streamlit app)
- **`requirements-local.txt`** (Full local dependencies including `streamlit`)
- **`.streamlit/config.toml`** (Theme & server settings)
- **`agents/`**, **`database/`**, **`models/`** (Project modules)

### Step 2: Connect to Streamlit Cloud
1. Go to [share.streamlit.io](https://share.streamlit.io/) and sign in with your GitHub account.
2. Click **"New app"**.
3. Select your repository: `Aniketyadav29/AgentForge`
4. Set the **Main file path** to: **`streamlit_app.py`**
5. Click **"Advanced settings..."** and add your Secrets / API keys:
   ```toml
   GEMINI_API_KEY = "your_gemini_api_key_here"
   GROQ_API_KEY = "your_groq_api_key_here"
   SERPER_API_KEY = "your_serper_api_key_here"
   ```
6. Click **"Deploy!"**

Your multi-agent AI research assistant will be live with a public URL! 🎉
