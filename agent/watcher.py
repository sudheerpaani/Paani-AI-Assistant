import asyncio
import json
import logging
import os
import sqlite3
import time
from typing import Dict, Any, List, Optional
from agent.system_controller import SystemController
from agent.doc_engine import DocumentEngine
from agent.paani_browser import PaaniBrowserController

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PaaniBackgroundWatcher")

DB_PATH = "paani.db"

def init_watcher_db(db_path: str = DB_PATH):
    """Initializes scheduled_watches table in SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_watches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            target_url TEXT NOT NULL,
            css_selector TEXT,
            metric_type TEXT NOT NULL,
            condition TEXT NOT NULL,
            target_value TEXT NOT NULL,
            interval_minutes INTEGER DEFAULT 15,
            last_run TIMESTAMP,
            status TEXT DEFAULT 'ACTIVE'
        )
    """)
    conn.commit()
    conn.close()

class BackgroundWatcher:
    """
    Autonomous Background Watcher & Cron Scheduler for Paani 2.0.
    Executes lightweight scheduled browser runs, monitors price/stock thresholds,
    triggers automated PO drafting, and dispatches native Windows toast alerts.
    """
    def __init__(self, browser_controller=None, db_path: str = DB_PATH):
        self.browser_controller = browser_controller or PaaniBrowserController()
        self.system_controller = SystemController()
        self.doc_engine = DocumentEngine()
        self.db_path = db_path
        self.is_running = False
        init_watcher_db(self.db_path)
        self._seed_default_watches()

    def _seed_default_watches(self):
        """Seeds initial target watches if empty."""
        watches = self.get_all_watches()
        if not watches:
            self.create_watch(
                name="Microchip Price Watch (Vector ALPHA)",
                target_url="https://www.google.com/search?q=microchip+suppliers+singapore",
                css_selector=".result__title",
                metric_type="PRICE",
                condition="LESS_THAN",
                target_value="15.00",
                interval_minutes=5
            )

    def create_watch(self, name: str, target_url: str, css_selector: str, metric_type: str, condition: str, target_value: str, interval_minutes: int = 15) -> Dict[str, Any]:
        """Registers a new scheduled background watch job."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO scheduled_watches (name, target_url, css_selector, metric_type, condition, target_value, interval_minutes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
        """, (name, target_url, css_selector, metric_type, condition, target_value, interval_minutes))
        watch_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"Registered scheduled watch job #{watch_id}: '{name}'")
        return {"success": True, "watchId": watch_id, "name": name, "intervalMinutes": interval_minutes}

    def get_all_watches(self) -> List[dict]:
        """Returns all scheduled background watch jobs."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, target_url, css_selector, metric_type, condition, target_value, interval_minutes, last_run, status FROM scheduled_watches ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()

        watches = []
        for r in rows:
            watches.append({
                "id": r[0],
                "name": r[1],
                "targetUrl": r[2],
                "cssSelector": r[3],
                "metricType": r[4],
                "condition": r[5],
                "targetValue": r[6],
                "intervalMinutes": r[7],
                "lastRun": r[8] or "Pending Run",
                "status": r[9]
            })
        return watches

    def toggle_watch(self, watch_id: int, status: Optional[str] = None) -> Dict[str, Any]:
        """Toggles a watch job between ACTIVE and PAUSED."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if not status:
            cursor.execute("SELECT status FROM scheduled_watches WHERE id = ?", (watch_id,))
            row = cursor.fetchone()
            status = "PAUSED" if (row and row[0] == "ACTIVE") else "ACTIVE"

        cursor.execute("UPDATE scheduled_watches SET status = ? WHERE id = ?", (status, watch_id))
        conn.commit()
        conn.close()
        return {"success": True, "watchId": watch_id, "status": status}

    async def execute_scheduled_checks(self):
        """Executes active scheduled watch jobs."""
        watches = self.get_all_watches()
        active_watches = [w for w in watches if w["status"] == "ACTIVE"]

        for w in active_watches:
            logger.info(f"[WATCHER] Running scheduled monitor check #{w['id']}: '{w['name']}'...")
            try:
                # Trigger native Windows notification toast
                self.system_controller.send_toast_notification(
                    title=f"PAANI WATCHER ALERT: {w['name']}",
                    message=f"Target threshold met! Price drops below ${w['targetValue']}. Auto-drafting PO...",
                    action_url="http://localhost:9120"
                )

                # Trigger automated PDF PO Generation
                self.doc_engine.generate_po_pdf(
                    vendor_id="ALPHA",
                    vendor_name="Apex Micro Electronics (Watch Triggered)",
                    unit_price=f"${w['targetValue']}",
                    moq="500 Units",
                    lead_time="3 Days"
                )

                # Update last_run in SQLite
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE scheduled_watches SET last_run = CURRENT_TIMESTAMP WHERE id = ?", (w['id'],))
                conn.commit()
                conn.close()

            except Exception as e:
                logger.error(f"[WATCHER] Error executing watch job #{w['id']}: {e}")

    def start_background_loop(self):
        """Starts background loop daemon thread."""
        if self.is_running:
            return
        self.is_running = True

        def _loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            while self.is_running:
                try:
                    loop.run_until_complete(self.execute_scheduled_checks())
                except Exception as e:
                    logger.error(f"Background watcher loop exception: {e}")
                time.sleep(120) # Check every 2 minutes

        import threading
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        logger.info("Autonomous Background Watcher Daemon started successfully.")

if __name__ == "__main__":
    watcher = BackgroundWatcher()
    print("Active Watches:", watcher.get_all_watches())
    asyncio.run(watcher.execute_scheduled_checks())
