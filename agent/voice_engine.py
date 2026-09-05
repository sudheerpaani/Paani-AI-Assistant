import asyncio
import base64
import io
import logging
import os
import tempfile
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PaaniVoiceEngine")

class VoiceEngine:
    """
    Lightweight, high-performance voice engine for Paani 2.0.
    Provides async TTS using edge-tts (or local SAPI/WebSpeech fallbacks)
    and STT transcription utilities.
    """
    def __init__(self, default_voice: str = "en-GB-RyanNeural"):
        self.default_voice = default_voice
        self.has_edge_tts = False
        self._check_dependencies()

    def _check_dependencies(self):
        try:
            import edge_tts
            self.has_edge_tts = True
            logger.info("edge-tts engine loaded successfully.")
        except ImportError:
            self.has_edge_tts = False
            logger.warning("edge-tts package not found. Will use fallback audio synthesis/client-side WebSpeech API.")

    def get_status(self) -> Dict[str, Any]:
        return {
            "available": True,
            "engine": "edge-tts" if self.has_edge_tts else "WebSpeechAPI-Fallback",
            "voice": self.default_voice,
            "stt": "WebSpeechAPI-Native"
        }

    async def synthesize(self, text: str, voice: Optional[str] = None) -> Dict[str, Any]:
        """Synthesizes text into MP3 audio bytes or base64 data."""
        if not text:
            return {"success": False, "error": "No text provided"}

        selected_voice = voice or self.default_voice

        if self.has_edge_tts:
            try:
                import edge_tts
                communicate = edge_tts.Communicate(text, selected_voice)
                fp = io.BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        fp.write(chunk["data"])
                
                audio_bytes = fp.getvalue()
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

                return {
                    "success": True,
                    "engine": "edge-tts",
                    "voice": selected_voice,
                    "mimeType": "audio/mpeg",
                    "audioB64": audio_b64,
                    "byteLength": len(audio_bytes)
                }
            except Exception as e:
                logger.error(f"edge-tts synthesis failed: {e}")

        # Fallback response for client-side WebSpeech synthesis
        return {
            "success": True,
            "engine": "WebSpeechAPI-Fallback",
            "text": text,
            "voice": selected_voice,
            "audioB64": None
        }

    def transcribe_audio_chunk(self, audio_bytes: bytes) -> Dict[str, Any]:
        """Fallback server-side STT routine if audio binary is posted."""
        try:
            import whisper
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                temp_path = f.name

            model = whisper.load_model("tiny.en")
            result = model.transcribe(temp_path)
            os.remove(temp_path)
            return {"success": True, "text": result.get("text", "").strip()}
        except Exception as e:
            return {
                "success": False,
                "error": f"Server STT fallback unavailable ({e}). Use client WebSpeech API.",
                "text": ""
            }

if __name__ == "__main__":
    engine = VoiceEngine()
    print("Voice Engine Status:", engine.get_status())
    async def test():
        res = await engine.synthesize("Directives processed. Vector Alpha identified top manufacturer Apex Micro Electronics.")
        print("Synthesis result:", res.get("success"), res.get("engine"), "Bytes:", res.get("byteLength"))
    asyncio.run(test())
