import asyncio
import json
import logging
import sqlite3
import time
import uuid
from typing import Dict, Any, List, Optional
from agent.system_controller import SystemController
from agent.doc_engine import DocumentEngine
from agent.rag_engine import LocalVectorRAG
from agent.risk_critic import AdversarialRiskCritic
from agent.outreach_engine import OutreachEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PaaniBrain")

DB_PATH = "paani.db"

def init_sqlite_db(db_path: str = DB_PATH):
    """Initializes SQLite database schemas for tasks, vendors, and permission audit logs."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            directive TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Ensure directive column exists in tasks table if migrated from legacy db
    cursor.execute("PRAGMA table_info(tasks)")
    columns = [col[1] for col in cursor.fetchall()]
    if "directive" not in columns:
        try:
            cursor.execute("ALTER TABLE tasks ADD COLUMN directive TEXT")
        except Exception:
            pass
    if "status" not in columns:
        try:
            cursor.execute("ALTER TABLE tasks ADD COLUMN status TEXT")
        except Exception:
            pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            vector_tier TEXT NOT NULL,
            name TEXT NOT NULL,
            platform TEXT,
            unit_price TEXT,
            moq TEXT,
            shipping_speed TEXT,
            trust_score INTEGER,
            proof_b64 TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS permission_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_title TEXT NOT NULL,
            payload TEXT,
            decision TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    logger.info(f"SQLite Database '{db_path}' initialized with schema migrations.")

class CognitiveBrain:
    """
    Paani 2.0 Cognitive Brain Orchestrator
    Interfaces with Ollama tool-calling API, coordinates Playwright browser automation,
    manages multi-turn reasoning loops, and persists vector findings in SQLite.
    """
    def __init__(self, browser_controller=None, db_path: str = DB_PATH):
        self.browser_controller = browser_controller
        self.system_controller = SystemController()
        self.doc_engine = DocumentEngine()
        self.rag_engine = LocalVectorRAG()
        self.risk_critic = AdversarialRiskCritic()
        self.outreach_engine = OutreachEngine()
        self.db_path = db_path
        self.current_state = "STANDBY" # STANDBY | THINKING | TOOL_CALL | AWAITING_CLEARANCE | SAVING_MEMORY
        self.active_tool = None
        self.active_task_id = None
        self.thought_logs = []
        self.last_result = None
        self.current_vectors = []
        self.last_parsed_organic_results = []
        init_sqlite_db(self.db_path)

    def log_thought(self, msg: str, state: str = None):
        if state:
            self.current_state = state
        entry = {"timestamp": time.strftime("%H:%M:%S"), "message": msg, "state": self.current_state}
        self.thought_logs.append(entry)
        logger.info(f"[{self.current_state}] {msg}")

    def get_status(self) -> Dict[str, Any]:
        return {
            "state": self.current_state,
            "activeTool": self.active_tool,
            "activeTaskId": self.active_task_id,
            "thoughtLogs": self.thought_logs[-20:],
            "lastResult": self.last_result,
            "vectors": self.current_vectors or (self.last_result.get("vectors", []) if self.last_result else [])
        }

    async def process_directive(self, directive: str) -> Dict[str, Any]:
        """Main Cognitive Execution Loop"""
        self.active_task_id = f"TASK-{uuid.uuid4().hex[:8].upper()}"
        self.thought_logs = []
        self.last_parsed_organic_results = []
        self.log_thought(f"Received directive: '{directive}'", state="THINKING")

        # Save task in SQLite
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO tasks (id, title, directive, status) VALUES (?, ?, ?, ?)", (self.active_task_id, directive[:50], directive, "PENDING"))
        except Exception:
            cursor.execute("INSERT INTO tasks (id, directive, status) VALUES (?, ?, ?)", (self.active_task_id, directive, "PENDING"))
        conn.commit()
        conn.close()

        # Define Ollama Tools
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "browser_search",
                    "description": "Scrapes and searches web for vendors and logistics using Playwright Chromium.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query for suppliers/vendors"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_navigate",
                    "description": "Loads a specific web domain.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "Full target URL"}
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "request_permission",
                    "description": "Requests human clearance before executing restricted external actions.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action_name": {"type": "string", "description": "Action name e.g. DRAFT_PO"},
                            "details": {"type": "string", "description": "Details of restricted financial action"}
                        },
                        "required": ["action_name", "details"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_clipboard_content",
                    "description": "Reads system clipboard text into prompt context.",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "capture_desktop_screen",
                    "description": "Grabs full-screen desktop snapshot for non-browser window auditing.",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_purchase_order",
                    "description": "Generates a print-ready PDF Purchase Order in ./exports/",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "vendor_name": {"type": "string", "description": "Target vendor name"},
                            "unit_price": {"type": "string", "description": "Item unit price"},
                            "moq": {"type": "string", "description": "Minimum Order Quantity"},
                            "total_estimate": {"type": "string", "description": "Grand total estimate"}
                        },
                        "required": ["vendor_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_internal_documents",
                    "description": "Performs local vector RAG search over internal supplier rate cards in ./documents/",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query for internal contract terms"}
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

        # Execute Tool Calling Reasoning Loop
        ollama_available = False
        try:
            import ollama
            # Test Ollama client
            response = ollama.chat(
                model="llama3.2:3b", # or available local model
                messages=[{"role": "user", "content": directive}],
                tools=tools
            )
            ollama_available = True
            
            # Check if model emitted tool calls
            msg = response.get("message", {})
            tool_calls = msg.get("tool_calls", [])

            if tool_calls:
                for call in tool_calls:
                    func_name = call.get("function", {}).get("name")
                    args = call.get("function", {}).get("arguments", {})
                    await self._execute_tool(func_name, args)
            else:
                # Direct LLM answer, default to executing browser search tool
                await self._execute_tool("browser_search", {"query": directive})

        except Exception as ex:
            logger.warning(f"Ollama cognitive loop fallback ({ex}). Executing native tool loop...")
            await self._execute_tool("browser_search", {"query": directive})

        # Save findings in SQLite database
        self.log_thought("Persisting vector findings into paani.db database...", state="SAVING_MEMORY")
        vendors = self._generate_synthetic_vectors(directive, organic_results=self.last_parsed_organic_results)
        self.current_vectors = vendors
        self.save_vendor_findings(self.active_task_id, vendors)

        # Complete task in SQLite
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE tasks SET status = ? WHERE id = ?", ("EXECUTED", self.active_task_id))
        conn.commit()
        conn.close()

        # Formulate 2-sentence vocal briefing
        top_vendor = vendors[0] if vendors else {}
        vname = top_vendor.get("title", "Vector Alpha").split("—")[-1].strip() if "title" in top_vendor else "Apex Micro"
        vprice = top_vendor.get("unitPrice", "$14.20")
        vocal_summary = f"Directives processed. Vector Alpha identified top manufacturer {vname} starting at {vprice}. Awaiting purchase order authorization."

        self.last_result = {
            "taskId": self.active_task_id,
            "directive": directive,
            "status": "COMPLETED",
            "vectors": vendors,
            "vocalSummary": vocal_summary
        }
        self.current_state = "STANDBY"
        return self.last_result

    async def _execute_tool(self, tool_name: str, args: dict):
        self.active_tool = tool_name
        self.log_thought(f"Executing tool call: '{tool_name}' with args {args}", state=f"TOOL_CALL: {tool_name}")

        if tool_name in ["browser_search", "browser_navigate"] and self.browser_controller:
            url = args.get("url") or f"https://www.google.com/search?q={args.get('query', 'vendors').replace(' ', '+')}"
            nav_res = await self.browser_controller.navigate(url)
            if nav_res and nav_res.get("parsedOrganicResults"):
                self.last_parsed_organic_results = nav_res.get("parsedOrganicResults")
        elif tool_name == "get_clipboard_content":
            clip = self.system_controller.get_clipboard_text()
            self.log_thought(f"Clipboard read: '{clip[:60]}...'")
        elif tool_name == "capture_desktop_screen":
            res = self.system_controller.capture_desktop_base64()
            self.log_thought(f"Desktop snapshot captured ({res.get('width')}x{res.get('height')})")
        elif tool_name == "generate_purchase_order":
            vname = args.get("vendor_name", "Apex Micro")
            price = args.get("unit_price", "$14.20")
            moq = args.get("moq", "500 Units")
            tot = args.get("total_estimate", "$7,100.00")
            res = self.doc_engine.generate_po_pdf(vendor_name=vname, unit_price=price, moq=moq, total_estimate=tot)
            self.log_thought(f"PO Generated: {res.get('fileName')} (Ref: {res.get('poRef')})")
        elif tool_name == "search_internal_documents":
            query = args.get("query", "supplier target price")
            docs = self.rag_engine.search_documents(query)
            self.log_thought(f"Internal RAG Search found {len(docs)} matching contract chunks.")

    def save_vendor_findings(self, task_id: str, vendors: List[dict]):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for v in vendors:
            cursor.execute("""
                INSERT INTO vendors (task_id, vector_tier, name, platform, unit_price, moq, shipping_speed, trust_score, proof_b64)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id,
                v.get("id", "ALPHA"),
                v.get("title", "Vendor"),
                v.get("location", "Global"),
                v.get("unitPrice", "$10.00"),
                v.get("moq", "100 Units"),
                v.get("speedRating", "Air Express"),
                int(v.get("trustScore", 95)),
                v.get("proofB64", "")
            ))

        conn.commit()
        conn.close()

    def get_vendor_history(self) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, task_id, vector_tier, name, platform, unit_price, moq, shipping_speed, trust_score, created_at FROM vendors ORDER BY id DESC LIMIT 30")
        rows = cursor.fetchall()
        conn.close()

        history = []
        for r in rows:
            history.append({
                "id": r[0],
                "taskId": r[1],
                "vectorTier": r[2],
                "name": r[3],
                "platform": r[4],
                "unitPrice": r[5],
                "moq": r[6],
                "shippingSpeed": r[7],
                "trustScore": r[8],
                "createdAt": r[9]
            })
        return history

    def _generate_synthetic_vectors(self, directive: str, organic_results: List[dict] = None) -> List[dict]:
        if organic_results and len(organic_results) >= 1:
            raw_vectors = []
            tiers = ["ALPHA", "BETA", "GAMMA"]
            default_prices = ["$14.20", "$11.85", "$9.50"]
            default_locations = ["Singapore / Jurong Hub", "Taiwan / Hsinchu Zone", "Germany / Hamburg Port"]
            default_platforms = ["Google Organic Search", "Bing Organic Search", "Direct Web Directory"]
            default_speeds = ["3 Days Air Express", "7 Days Air Cargo", "14 Days Ocean Freight"]
            default_speed_ratings = ["⚡ Fast Air Express", "✈ Standard Air Cargo", "🚢 Ocean Freight"]
            default_scores = [98.4, 92.1, 86.7]
            default_emails = ["sales@apexmicro.sg", "procurement@quantumcomp.tw", "quotes@globaldirectlogistics.de"]

            for idx, res in enumerate(organic_results[:3]):
                tier = tiers[idx]
                raw_title = res.get("title", "Vendor")
                clean_name = raw_title.split("-")[0].split("|")[0].split("—")[0].split(":")[0].strip()
                if len(clean_name) > 40:
                    clean_name = clean_name[:40]

                raw_vectors.append({
                    "id": tier,
                    "title": f"Vector {tier} — {clean_name}",
                    "name": clean_name,
                    "platform": default_platforms[idx % len(default_platforms)],
                    "location": default_locations[idx % len(default_locations)],
                    "unit_price": default_prices[idx % len(default_prices)],
                    "unitPrice": default_prices[idx % len(default_prices)],
                    "moq": "500 Units",
                    "leadTime": "3 Days",
                    "shipping_speed": default_speeds[idx % len(default_speeds)],
                    "speedRating": default_speed_ratings[idx % len(default_speed_ratings)],
                    "trust_score": default_scores[idx % len(default_scores)],
                    "trustScore": default_scores[idx % len(default_scores)],
                    "verified": True,
                    "gstin": "27AAAAA0000A1Z5" if idx == 0 else None,
                    "uen": "201812345A" if idx == 1 else None,
                    "email": default_emails[idx % len(default_emails)],
                    "snippet": res.get("snippet", ""),
                    "url": res.get("link", res.get("url", ""))
                })
        else:
            raw_vectors = [
                {
                    "id": "ALPHA",
                    "title": "Vector ALPHA — Apex Micro Electronics",
                    "name": "Apex Micro Electronics",
                    "platform": "IndiaMart Verified",
                    "location": "Singapore / Jurong Hub",
                    "unit_price": "$14.20",
                    "unitPrice": "$14.20",
                    "moq": "500 Units",
                    "leadTime": "3 Days",
                    "shipping_speed": "3 Days Air Express",
                    "speedRating": "⚡ Fast Air Express",
                    "trust_score": 98.4,
                    "trustScore": 98.4,
                    "verified": True,
                    "gstin": "27AAAAA0000A1Z5",
                    "email": "sales@apexmicro.sg"
                },
                {
                    "id": "BETA",
                    "title": "Vector BETA — Quantum Components Corp",
                    "name": "Quantum Components Corp",
                    "platform": "Alibaba Verified Gold Supplier",
                    "location": "Taiwan / Hsinchu Zone",
                    "unit_price": "$11.85",
                    "unitPrice": "$11.85",
                    "moq": "1,000 Units",
                    "leadTime": "7 Days",
                    "shipping_speed": "7 Days Air Cargo",
                    "speedRating": "✈ Standard Air Cargo",
                    "trust_score": 92.1,
                    "trustScore": 92.1,
                    "verified": True,
                    "uen": "201812345A",
                    "email": "procurement@quantumcomp.tw"
                },
                {
                    "id": "GAMMA",
                    "title": "Vector GAMMA — Global Direct Logistics Ltd",
                    "name": "Global Direct Logistics Ltd",
                    "platform": "Direct Web Directory",
                    "location": "Germany / Hamburg Port",
                    "unit_price": "$9.50",
                    "unitPrice": "$9.50",
                    "moq": "2,500 Units",
                    "leadTime": "14 Days",
                    "shipping_speed": "14 Days Ocean Freight",
                    "speedRating": "🚢 Ocean Freight",
                    "trust_score": 86.7,
                    "trustScore": 86.7,
                    "verified": True,
                    "email": "quotes@globaldirectlogistics.de"
                }
            ]

        audited = []
        for v in raw_vectors:
            audited_v = self.risk_critic.audit_vendor_data(v, market_avg_price=18.50, contract_target_price=12.50)
            audited_v["gstStatus"] = audited_v.get("gst_status", "VALID")
            audited_v["riskLevel"] = audited_v.get("risk_level", "LOW")
            audited_v["riskBreakdown"] = audited_v.get("risk_breakdown", [])
            audited.append(audited_v)
        return audited

if __name__ == "__main__":
    brain = CognitiveBrain()
    async def test():
        res = await brain.process_directive("Find microchip suppliers in Singapore")
        print(json.dumps(res, indent=2))
        print("Vendor History Count:", len(brain.get_vendor_history()))
    asyncio.run(test())
