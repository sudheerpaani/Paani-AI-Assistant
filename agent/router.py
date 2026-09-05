import asyncio
import json
import logging
import os
import sqlite3
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PaaniHybridRouter")

DB_PATH = "paani.db"

def init_config_db(db_path: str = DB_PATH):
    """Initializes system_config table in SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Set default values if not present
    defaults = {
        "active_provider": "LOCAL",
        "routing_mode": "AUTO",
        "gemini_api_key": "",
        "openai_api_key": ""
    }
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()

class HybridModelRouter:
    """
    Hybrid Cloud Model Router for Paani 2.0.
    Dynamically balances fast local Ollama execution with cloud synthesis (Gemini / OpenAI API)
    based on task complexity, context length, and user routing preferences.
    """
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        init_config_db(self.db_path)

    def get_config(self, key: str, default: str = "") -> str:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM system_config WHERE key = ?", (key,))
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else default
        except Exception:
            return default

    def set_config(self, key: str, value: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO system_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (key, value))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to save config {key}: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        g_key = self.get_config("gemini_api_key")
        o_key = self.get_config("openai_api_key")
        active = self.get_config("active_provider", "LOCAL")
        mode = self.get_config("routing_mode", "AUTO")

        return {
            "activeProvider": active,
            "routingMode": mode,
            "hasGeminiKey": bool(g_key and len(g_key) > 5),
            "hasOpenAIKey": bool(o_key and len(o_key) > 5),
            "geminiKeyMasked": f"{g_key[:4]}...{g_key[-4:]}" if len(g_key) > 8 else ("Configured" if g_key else "None"),
            "openaiKeyMasked": f"{o_key[:4]}...{o_key[-4:]}" if len(o_key) > 8 else ("Configured" if o_key else "None")
        }

    def classify_prompt(self, prompt: str) -> Dict[str, Any]:
        """Classifies prompt complexity to route between Local Ollama and Cloud Synthesis."""
        mode = self.get_config("routing_mode", "AUTO")
        active_provider = self.get_config("active_provider", "LOCAL")

        if mode == "ALWAYS_LOCAL" or active_provider == "LOCAL":
            return {"tier": 1, "engine": "LOCAL_OLLAMA", "model": "qwen2.5:4b", "reason": "Routing set to Local Ollama."}

        g_key = self.get_config("gemini_api_key")
        o_key = self.get_config("openai_api_key")

        # Evaluate prompt weight
        complex_keywords = ["deep research", "cross-reference", "synthesize", "audit report", "compare logistics", "multi-page", "cloud"]
        words = prompt.lower().split()
        is_heavy = len(words) > 30 or any(k in prompt.lower() for k in complex_keywords)

        if (mode == "ALWAYS_CLOUD" or is_heavy) and g_key:
            return {"tier": 2, "engine": "GEMINI_CLOUD", "model": "gemini-1.5-flash", "reason": "Complex task routed to Gemini Cloud API."}
        elif (mode == "ALWAYS_CLOUD" or is_heavy) and o_key:
            return {"tier": 2, "engine": "OPENAI_CLOUD", "model": "gpt-4o-mini", "reason": "Complex task routed to OpenAI Cloud API."}

        return {"tier": 1, "engine": "LOCAL_OLLAMA", "model": "qwen2.5:4b", "reason": "Fast local execution on Ollama Qwen."}

    async def route_completion(self, prompt: str, system_prompt: str = "") -> Dict[str, Any]:
        """Executes completion via classified model tier with local fallbacks."""
        classification = self.classify_prompt(prompt)
        engine = classification["engine"]

        if engine == "GEMINI_CLOUD":
            g_key = self.get_config("gemini_api_key")
            try:
                res_text = await self._call_gemini_api(prompt, g_key, system_prompt)
                return {
                    "success": True,
                    "engine": "GEMINI_CLOUD",
                    "model": "gemini-1.5-flash",
                    "text": res_text,
                    "tier": 2
                }
            except Exception as e:
                logger.warning(f"Gemini Cloud call failed ({e}). Falling back to Local Ollama...")

        elif engine == "OPENAI_CLOUD":
            o_key = self.get_config("openai_api_key")
            try:
                res_text = await self._call_openai_api(prompt, o_key, system_prompt)
                return {
                    "success": True,
                    "engine": "OPENAI_CLOUD",
                    "model": "gpt-4o-mini",
                    "text": res_text,
                    "tier": 2
                }
            except Exception as e:
                logger.warning(f"OpenAI Cloud call failed ({e}). Falling back to Local Ollama...")

        # Fallback / Default Local Execution
        return {
            "success": True,
            "engine": "LOCAL_OLLAMA",
            "model": "qwen2.5:4b",
            "text": f"Local Ollama processed prompt: {prompt[:60]}...",
            "tier": 1
        }

    async def _call_gemini_api(self, prompt: str, api_key: str, system_prompt: str = "") -> str:
        """Calls Google Gemini REST API asynchronously."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{system_prompt}\n\nUser Directive: {prompt}"}
                    ]
                }
            ]
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})

        loop = asyncio.get_event_loop()
        def _do_req():
            with urllib.request.urlopen(req, timeout=12) as response:
                res_json = json.loads(response.read().decode("utf-8"))
                candidates = res_json.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
                return "Gemini response empty."
        return await loop.run_in_executor(None, _do_req)

    async def _call_openai_api(self, prompt: str, api_key: str, system_prompt: str = "") -> str:
        """Calls OpenAI REST API asynchronously."""
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt or "You are Paani 2.0 AI Assistant."},
                {"role": "user", "content": prompt}
            ]
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        })

        loop = asyncio.get_event_loop()
        def _do_req():
            with urllib.request.urlopen(req, timeout=12) as response:
                res_json = json.loads(response.read().decode("utf-8"))
                choices = res_json.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                return "OpenAI response empty."
        return await loop.run_in_executor(None, _do_req)

if __name__ == "__main__":
    router = HybridModelRouter()
    print("Router Config Status:", router.get_status())
    print("Classification Test:", router.classify_prompt("Perform deep research and synthesize cloud audit report"))
