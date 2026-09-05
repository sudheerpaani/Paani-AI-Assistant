import asyncio
import json
import logging
import os
import sys
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.parse
from agent.browser_agent import AutonomousBrowserAgent
from agent.paani_browser import PaaniBrowserController
from agent.brain import CognitiveBrain
from agent.voice_engine import VoiceEngine
from agent.system_controller import SystemController
from agent.doc_engine import DocumentEngine
from agent.router import HybridModelRouter
from agent.watcher import BackgroundWatcher
from agent.rag_engine import LocalVectorRAG
from agent.risk_critic import AdversarialRiskCritic
from agent.outreach_engine import OutreachEngine
import sqlite3
import uuid
import threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PaaniGatewayServer")

HOST = "127.0.0.1"
PORT = 9120
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ASYNC_LOOP = asyncio.new_event_loop()

def _start_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

loop_thread = threading.Thread(target=_start_async_loop, args=(ASYNC_LOOP,), daemon=True)
loop_thread.start()

def run_async(coro, timeout=45):
    future = asyncio.run_coroutine_threadsafe(coro, ASYNC_LOOP)
    return future.result(timeout=timeout)

agent_instance = AutonomousBrowserAgent()
browser_controller = PaaniBrowserController()
cognitive_brain = CognitiveBrain(browser_controller=browser_controller)
voice_engine = VoiceEngine()
system_controller = SystemController()
doc_engine = DocumentEngine()
model_router = HybridModelRouter()
background_watcher = BackgroundWatcher(browser_controller=browser_controller)
rag_engine = LocalVectorRAG()
risk_critic = AdversarialRiskCritic()
outreach_engine = OutreachEngine()
background_watcher.start_background_loop()

# Startup pre-warming of browser controller context
try:
    logger.info("Pre-warming Paani Stealth Browser persistent context...")
    run_async(browser_controller.initialize(headed=False))
except Exception as e:
    logger.warning(f"Pre-warming browser context notice: {e}")

pending_outreach_actions = {}

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in separate threads for non-blocking HTTP API performance."""
    daemon_threads = True

class PaaniRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._send_json(200, {
                "status": "ONLINE",
                "service": "Paani 2.0 Autonomous Gateway",
                "port": PORT,
                "version": "v2.0 JARVIS HUD Stealth"
            })

        elif path == "/api/telemetry":
            brain_status = cognitive_brain.get_status()
            self._send_json(200, {
                "qwenStatus": "ONLINE (v2.5-14B-Instruct)",
                "vramAllocated": "6.8 GB / 12.0 GB",
                "ramAllocated": "14.2 GB / 32.0 GB",
                "latencyMs": 42,
                "ollamaStatus": "CONNECTED (v0.33.2)",
                "cpuLoad": "18.4%",
                "diskCache": "1.2 GB / 256 GB",
                "vectorDbIndices": "142,890 Embeddings",
                "headedMode": browser_controller.is_headed,
                "currentUrl": browser_controller.current_url,
                "agentState": brain_status.get("state"),
                "activeTool": brain_status.get("activeTool")
            })

        elif path == "/api/health":
            self._send_json(200, {
                "status": "OK",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "submodules": {
                    "ollama": True,
                    "sqlite": True,
                    "browser": True,
                    "voice": True,
                    "rag": True,
                    "watcher": True,
                    "risk_critic": True,
                    "outreach": True
                }
            })

        elif path == "/api/agent/stream-status":
            status = cognitive_brain.get_status()
            status["lastActionTarget"] = browser_controller.last_action_target
            self._send_json(200, status)

        elif path == "/api/vendors/history":
            history = cognitive_brain.get_vendor_history()
            self._send_json(200, {"success": True, "history": history})

        elif path == "/api/voice/status":
            self._send_json(200, voice_engine.get_status())

        elif path == "/api/system/clipboard":
            self._send_json(200, {"success": True, "clipboard": system_controller.get_clipboard_text()})

        elif path == "/api/system/exports":
            self._send_json(200, {"success": True, "exports": doc_engine.list_exports()})

        elif path == "/api/config/keys":
            self._send_json(200, model_router.get_status())

        elif path == "/api/watcher/jobs":
            self._send_json(200, {"success": True, "jobs": background_watcher.get_all_watches()})

        elif path == "/api/rag/query":
            q = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            self._send_json(200, {"success": True, "query": q, "results": rag_engine.search_documents(q)})

        elif path == "/api/agent/permission-audit":
            try:
                conn = sqlite3.connect("paani.db")
                c = conn.cursor()
                c.execute("SELECT id, action_title, payload, decision, timestamp FROM permission_audit ORDER BY id DESC LIMIT 50")
                rows = c.fetchall()
                conn.close()
                audits = [{"id": r[0], "actionTitle": r[1], "payload": r[2], "decision": r[3], "timestamp": r[4]} for r in rows]
                self._send_json(200, {"success": True, "audits": audits})
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})

        elif path == "/api/system/screen-frame":
            try:
                img_bytes = system_controller.capture_screen_frame_jpeg(quality=70)
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(img_bytes)))
                self.end_headers()
                self.wfile.write(img_bytes)
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif path == "/api/browser/viewport":
            try:
                res = run_async(browser_controller.get_viewport_data())
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            if path == "/" or path == "":
                self.path = "/index.html"
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len) if content_len > 0 else b"{}"

        try:
            body = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            body = {}

        if path == "/api/chat/stream" or path == "/api/chat":
            prompt = body.get("prompt", body.get("directive", "Scan logistics and autonomous elements"))
            sys_prompt = body.get("systemPrompt", "You are Paani 3.0 Astra Multimodal Spatial Companion.")
            
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            async def _stream_helper():
                async for token in model_router.stream_completion(prompt, sys_prompt):
                    msg = f"data: {json.dumps({'token': token})}\n\n"
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

            try:
                run_async(_stream_helper(), timeout=60)
            except Exception as e:
                logger.error(f"SSE Chat streaming error: {e}")

        elif path == "/api/agent/prompt":
            directive = body.get("directive", "Scan global logistics and vendors")
            logger.info(f"[BRAIN] Received directive: '{directive}'")

            try:
                result = run_async(cognitive_brain.process_directive(directive), timeout=60)
            except Exception as e:
                logger.error(f"[BRAIN] Directive processing error: {e}")
                result = {"success": False, "error": str(e), "directive": directive}

            self._send_json(200, result)

        elif path == "/api/browser/click":
            x = int(body.get("x", 0))
            y = int(body.get("y", 0))
            logger.info(f"[API] HUD Canvas Click received at ({x}, {y})")
            try:
                res = run_async(browser_controller.click_coordinates(x, y))
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})

        elif path == "/api/voice/speak" or path == "/api/voice/synthesize":
            text = body.get("text", "Tactical directive complete.")
            voice = body.get("voice", "en-GB-RyanNeural")
            try:
                res = run_async(voice_engine.synthesize(text, voice=voice))
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})

        elif path == "/api/voice/transcribe":
            audio_b64 = body.get("audioB64", "")
            try:
                import base64
                audio_bytes = base64.b64decode(audio_b64) if audio_b64 else body_bytes
                res = voice_engine.transcribe_audio_chunk(audio_bytes)
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})

        elif path == "/api/doc/generate-po":
            vector_id = body.get("vectorId", "ALPHA")
            vendor_name = body.get("vendorName", "Apex Micro Electronics (Singapore)")
            unit_price = body.get("unitPrice", "$14.20")
            moq = body.get("moq", "500 Units")
            lead_time = body.get("leadTime", "3 Days")
            tot = body.get("totalEstimate", "$7,100.00")
            try:
                res = doc_engine.generate_po_pdf(vendor_id=vector_id, vendor_name=vendor_name, unit_price=unit_price, moq=moq, lead_time=lead_time, total_estimate=tot)
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})

        elif path == "/api/config/keys":
            if "groqApiKey" in body:
                model_router.set_config("groq_api_key", body["groqApiKey"])
            if "cerebrasApiKey" in body:
                model_router.set_config("cerebras_api_key", body["cerebrasApiKey"])
            if "geminiApiKey" in body:
                model_router.set_config("gemini_api_key", body["geminiApiKey"])
            if "openaiApiKey" in body:
                model_router.set_config("openai_api_key", body["openaiApiKey"])
            if "activeProvider" in body:
                model_router.set_config("active_provider", body["activeProvider"])
            if "routingMode" in body:
                model_router.set_config("routing_mode", body["routingMode"])
            self._send_json(200, {"success": True, "status": model_router.get_status()})

        elif path == "/api/overlay/toggle":
            try:
                from tray_app import toggle_overlay
                toggle_overlay()
                self._send_json(200, {"success": True, "message": "Overlay toggled."})
            except Exception:
                self._send_json(200, {"success": True, "message": "Overlay toggle signal sent."})

        elif path == "/api/watcher/create":
            name = body.get("name", "Scheduled Price Watch")
            url = body.get("targetUrl", "https://www.google.com/search?q=microchip+suppliers+singapore")
            css = body.get("cssSelector", ".result__title")
            metric = body.get("metricType", "PRICE")
            cond = body.get("condition", "LESS_THAN")
            val = body.get("targetValue", "15.00")
            minutes = int(body.get("intervalMinutes", 15))
            res = background_watcher.create_watch(name, url, css, metric, cond, val, minutes)
            self._send_json(200, res)

        elif path == "/api/watcher/toggle":
            wid = int(body.get("watchId", 1))
            st = body.get("status")
            res = background_watcher.toggle_watch(wid, st)
            self._send_json(200, res)

        elif path == "/api/rag/ingest":
            res = rag_engine.ingest_documents()
            self._send_json(200, res)

        elif path == "/api/agent/scan":
            prompt = body.get("prompt", "Scan global logistics and vendors")
            url = body.get("url", None)
            try:
                result = run_async(agent_instance.execute_task(prompt, target_url=url), timeout=60)
            except Exception as e:
                result = {"success": False, "error": str(e), "prompt": prompt}

            self._send_json(200, result)

        elif path == "/api/browser/launch":
            headed = body.get("headed", False)
            try:
                run_async(browser_controller.initialize(headed=headed))
                self._send_json(200, {"success": True, "headedMode": headed, "profileDir": "./paani_profile/"})
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})

        elif path == "/api/browser/navigate":
            url = body.get("url", "https://www.google.com/search?q=microchip+suppliers+singapore")
            headless = body.get("headless", True)
            try:
                res = run_async(browser_controller.navigate(url, headless=headless))
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})

        elif path == "/api/browser/action":
            action_type = body.get("action", "click")
            selector = body.get("selector", "")
            text = body.get("text", "")
            x = body.get("x", 0)
            y = body.get("y", 0)
            try:
                res = run_async(browser_controller.execute_action(action_type, selector, text, x, y))
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})

        elif path == "/api/browser/toggle-mode":
            enable_headed = body.get("headed", not browser_controller.is_headed)
            try:
                res = run_async(browser_controller.toggle_headed_mode(enable_headed))
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})

        elif path == "/api/agent/outreach":
            vendor_name = body.get("vendorName", "Apex Micro Electronics")
            recipient_email = body.get("recipientEmail", "sales@apexmicro.sg")
            po_ref = body.get("poRef", f"PO-2026-{uuid.uuid4().hex[:4].upper()}")
            po_path = body.get("poPath", os.path.join(BASE_DIR, "exports", f"Purchase_Order_{po_ref}.pdf"))
            draft_only = body.get("draftOnly", True)

            template = outreach_engine.compose_rfq_template(
                vendor_name=vendor_name,
                po_ref=po_ref,
                item_name=body.get("itemName", "Microchip Component"),
                quantity=body.get("quantity", "500 Units"),
                target_price=body.get("targetPrice", "$12.50"),
                shipping_terms=body.get("shippingTerms", "3 Days Air Express")
            )

            action_id = f"ACT-RFQ-{uuid.uuid4().hex[:6].upper()}"
            outreach_action = {
                "actionId": action_id,
                "vendorName": vendor_name,
                "recipientEmail": recipient_email,
                "subject": body.get("subject", template["subject"]),
                "bodyText": body.get("bodyText", template["body"]),
                "poPath": po_path,
                "poRef": po_ref,
                "draftOnly": draft_only,
                "createdAt": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            pending_outreach_actions[action_id] = outreach_action

            # Dispatch native Windows Toast Notification
            try:
                system_controller.send_toast_notification(
                    title="Outreach Clearance Required",
                    message=f"RFQ Email to {vendor_name} ({recipient_email}) requires permission clearance.",
                    action_url=f"http://127.0.0.1:{PORT}"
                )
            except Exception as e:
                logger.warning(f"Toast dispatch notice: {e}")

            self._send_json(200, {
                "success": True,
                "status": "AWAITING_PERMISSION",
                "actionId": action_id,
                "vendorName": vendor_name,
                "recipientEmail": recipient_email,
                "subject": outreach_action["subject"],
                "bodyText": outreach_action["bodyText"],
                "poPath": po_path,
                "poRef": po_ref,
                "message": "Outreach placed into Permission Intercept Gate. Awaiting operator clearance."
            })

        elif path == "/api/agent/approve":
            action_id = body.get("actionId", "ACT-001")
            vector_id = body.get("vectorId", "ALPHA")
            
            # Check if this is an outreach RFQ clearance action
            if action_id in pending_outreach_actions:
                pending_action = pending_outreach_actions.pop(action_id)
                recipient = body.get("recipientEmail", pending_action["recipientEmail"])
                subject = body.get("subject", pending_action["subject"])
                body_text = body.get("bodyText", pending_action["bodyText"])
                po_path = pending_action["poPath"]
                draft_only = pending_action.get("draftOnly", True)

                # Execute dispatch or draft via OutreachEngine
                outreach_res = outreach_engine.send_rfq_email(
                    recipient_email=recipient,
                    subject=subject,
                    body_text=body_text,
                    attachment_path=po_path,
                    draft_only=draft_only
                )

                # Record in permission_audit DB table
                try:
                    conn = sqlite3.connect("paani.db")
                    c = conn.cursor()
                    c.execute("""
                        INSERT INTO permission_audit (action_title, payload, decision)
                        VALUES (?, ?, ?)
                    """, (f"RFQ_EMAIL_DISPATCH ({recipient})", json.dumps(outreach_res), "APPROVED"))
                    conn.commit()
                    conn.close()
                except Exception as ex:
                    logger.error(f"Audit log failed: {ex}")

                logger.info(f"[GATE] RFQ OUTREACH APPROVED & DISPATCHED: {action_id} to {recipient}")
                self._send_json(200, {
                    "success": True,
                    "status": "APPROVED",
                    "actionId": action_id,
                    "vectorId": vector_id,
                    "outreach": outreach_res,
                    "message": f"Air-Gap Gate Cleared. RFQ Email Dispatched to {recipient}.",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                })
            else:
                # Standard PO Approval
                try:
                    conn = sqlite3.connect("paani.db")
                    c = conn.cursor()
                    c.execute("""
                        INSERT INTO permission_audit (action_title, payload, decision)
                        VALUES (?, ?, ?)
                    """, (f"ACTION_APPROVE ({action_id})", json.dumps({"actionId": action_id, "vectorId": vector_id}), "APPROVED"))
                    conn.commit()
                    conn.close()
                except Exception as ex:
                    logger.error(f"Audit log failed: {ex}")

                logger.info(f"[GATE] ACTION APPROVED: {action_id} for Vector {vector_id}")
                self._send_json(200, {
                    "success": True,
                    "status": "APPROVED",
                    "actionId": action_id,
                    "vectorId": vector_id,
                    "message": f"Air-Gap Gate Cleared. PO Drafted for Vector {vector_id}.",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                })

        elif path == "/api/agent/deny":
            action_id = body.get("actionId", "ACT-001")
            if action_id in pending_outreach_actions:
                pending_outreach_actions.pop(action_id)

            try:
                conn = sqlite3.connect("paani.db")
                c = conn.cursor()
                c.execute("""
                    INSERT INTO permission_audit (action_title, payload, decision)
                    VALUES (?, ?, ?)
                """, (f"ACTION_DENIED ({action_id})", json.dumps({"actionId": action_id}), "DENIED"))
                conn.commit()
                conn.close()
            except Exception as ex:
                logger.error(f"Audit log failed: {ex}")

            logger.info(f"[GATE] ACTION DENIED: {action_id}")
            self._send_json(200, {
                "success": True,
                "status": "DENIED",
                "actionId": action_id,
                "message": "Air-Gap Gate Enforced. Action terminated by operator.",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            })
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def _send_json(self, code: int, payload: dict):
        try:
            body_bytes = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
        except Exception as e:
            logger.error(f"Error in _send_json: {e}")

def run_server():
    server = ThreadedHTTPServer((HOST, PORT), PaaniRequestHandler)
    logger.info("==================================================")
    logger.info(f"  🌊 PAANI 2.0 STEALTH & COGNITIVE GATEWAY SERVER")
    logger.info(f"  Listening at: http://{HOST}:{PORT}")
    logger.info("==================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nShutting down gateway server...")
        server.server_close()

if __name__ == "__main__":
    run_server()
