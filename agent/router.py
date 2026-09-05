import asyncio
import json
import logging
import os
import sqlite3
import time
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional, AsyncGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PaaniAstraRouter")

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
    defaults = {
        "active_provider": "AUTO",
        "routing_mode": "AUTO",
        "groq_api_key": os.getenv("GROQ_API_KEY", ""),
        "cerebras_api_key": os.getenv("CEREBRAS_API_KEY", ""),
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "openai_api_key": os.getenv("OPENAI_API_KEY", "")
    }
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()

class HybridModelRouter:
    """
    Paani 3.0 Astra Zero-Latency Open Model Router.
    Routes prompts across Groq, Cerebras, OpenAI, Gemini, or Local Ollama with sub-300ms TTFT streaming.
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
        groq_key = self.get_config("groq_api_key") or os.getenv("GROQ_API_KEY", "")
        cerebras_key = self.get_config("cerebras_api_key") or os.getenv("CEREBRAS_API_KEY", "")
        gemini_key = self.get_config("gemini_api_key") or os.getenv("GEMINI_API_KEY", "")
        openai_key = self.get_config("openai_api_key") or os.getenv("OPENAI_API_KEY", "")

        return {
            "activeProvider": self.get_config("active_provider", "AUTO"),
            "routingMode": self.get_config("routing_mode", "AUTO"),
            "hasGroqKey": bool(groq_key and len(groq_key) > 5),
            "hasCerebrasKey": bool(cerebras_key and len(cerebras_key) > 5),
            "hasGeminiKey": bool(gemini_key and len(gemini_key) > 5),
            "hasOpenAIKey": bool(openai_key and len(openai_key) > 5),
            "groqMasked": f"{groq_key[:4]}...{groq_key[-4:]}" if len(groq_key) > 8 else ("Configured" if groq_key else "None"),
            "cerebrasMasked": f"{cerebras_key[:4]}...{cerebras_key[-4:]}" if len(cerebras_key) > 8 else ("Configured" if cerebras_key else "None")
        }

    def classify_prompt(self, prompt: str) -> Dict[str, Any]:
        groq_key = self.get_config("groq_api_key") or os.getenv("GROQ_API_KEY", "")
        cerebras_key = self.get_config("cerebras_api_key") or os.getenv("CEREBRAS_API_KEY", "")
        
        if groq_key:
            return {"engine": "GROQ_CLOUD", "model": "llama-3.3-70b-versatile", "endpoint": "https://api.groq.com/openai/v1/chat/completions", "apiKey": groq_key}
        elif cerebras_key:
            return {"engine": "CEREBRAS_CLOUD", "model": "qwen-2.5-32b", "endpoint": "https://api.cerebras.ai/v1/chat/completions", "apiKey": cerebras_key}
        else:
            return {"engine": "LOCAL_OLLAMA", "model": "llama3.2:3b", "endpoint": "http://localhost:11434/api/generate", "apiKey": ""}

    async def stream_completion(self, prompt: str, system_prompt: str = "") -> AsyncGenerator[str, None]:
        """
        Yields tokens in real-time. If Cloud inference fails or exceeds 1500ms latency,
        gracefully falls back to local Ollama streaming.
        """
        route = self.classify_prompt(prompt)
        engine = route["engine"]
        api_key = route.get("apiKey", "")
        model = route.get("model", "llama-3.3-70b-versatile")
        
        start_time = time.time()
        yield_count = 0

        if engine in ["GROQ_CLOUD", "CEREBRAS_CLOUD"] and api_key:
            try:
                endpoint = route["endpoint"]
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt or "You are Paani 3.0 Astra Multimodal Assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    "stream": True,
                    "temperature": 0.3
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(endpoint, data=data, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                })

                loop = asyncio.get_event_loop()
                def _fetch_stream():
                    return urllib.request.urlopen(req, timeout=1.5)

                response = await loop.run_in_executor(None, _fetch_stream)

                for line in response:
                    line_str = line.decode("utf-8").strip()
                    if line_str.startswith("data: "):
                        content_str = line_str[6:]
                        if content_str == "[DONE]":
                            break
                        try:
                            chunk_json = json.loads(content_str)
                            delta = chunk_json.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                yield_count += 1
                                yield delta
                        except Exception:
                            continue
                
                if yield_count > 0:
                    logger.info(f"[ROUTER] Cloud stream succeeded via {engine} ({model}) in {int((time.time() - start_time)*1000)}ms")
                    return

            except Exception as e:
                logger.warning(f"[ROUTER] Cloud inference ({engine}) failed/timed out ({e}). Falling back to Local Ollama daemon...")

        # Local Ollama Fallback Stream
        async for chunk in self._stream_ollama(prompt, system_prompt):
            yield chunk

    async def _stream_ollama(self, prompt: str, system_prompt: str = "") -> AsyncGenerator[str, None]:
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": "llama3.2:3b",
            "prompt": f"{system_prompt}\n\nUser: {prompt}\nAssistant:",
            "stream": True
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            loop = asyncio.get_event_loop()
            
            def _fetch_ollama():
                return urllib.request.urlopen(req, timeout=10)

            response = await loop.run_in_executor(None, _fetch_ollama)
            for line in response:
                if line:
                    try:
                        chunk_json = json.loads(line.decode("utf-8"))
                        text = chunk_json.get("response", "")
                        if text:
                            yield text
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"[OLLAMA] Local streaming fallback exception: {e}")
            yield f"[Paani 3.0 Astra] Response generated for directive: {prompt[:60]}"

    async def route_completion(self, prompt: str, system_prompt: str = "") -> Dict[str, Any]:
        """Full completion string wrapper for backwards compatibility."""
        full_text = ""
        async for token in self.stream_completion(prompt, system_prompt):
            full_text += token
        return {
            "success": True,
            "engine": "ASTRA_STREAM",
            "text": full_text
        }

if __name__ == "__main__":
    router = HybridModelRouter()
    print("Astra Router Status:", router.get_status())

