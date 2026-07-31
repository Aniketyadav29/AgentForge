import os
import sys
import urllib.request
import json
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
print("GEMINI_API_KEY in .env:", repr(gemini_key))

topic = "tell me about the visitable places in india in detai in table format."
depth = "detailed"

models_to_try = [
    "gemini-2.5-flash",
    "gemini-1.5-flash",
    "gemini-2.0-flash",
]

system_instruction = (
    "You are an expert AI research assistant. Your task is to provide a comprehensive, "
    "accurate, highly structured, and friendly answer directly addressing the user's request. "
    "IMPORTANT RULES:\n"
    "1. Strictly answer what the user asked for. If they requested a table, use Markdown tables. "
    "If they asked in Hinglish or Hindi, write in Hinglish or Hindi. If they asked for places/recommendations, "
    "provide specific real names, details, travel modes, costs, and highlights.\n"
    "2. Do NOT output generic business reports or canned templates unless explicitly asked for market analysis.\n"
    "3. Format cleanly with Markdown headings, bullet points, and tables."
)

user_prompt = f"User Request: {topic}\nResearch Depth: {depth}\n"

for model in models_to_try:
    print(f"Testing model: {model}...")
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        payload = {
            "contents": [{"parts": [{"text": f"{system_instruction}\n\n{user_prompt}"}]}]
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=35) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            text = res_data["candidates"][0]["content"]["parts"][0]["text"]
            print("SUCCESS! Model", model, "returned response length:", len(text))
            print("Preview:\n", text[:300])
            break
    except Exception as ge:
        print(f"Model {model} failed with error:", ge)
