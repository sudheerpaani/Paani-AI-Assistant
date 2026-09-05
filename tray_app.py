import logging
import os
import sys
import threading
import time
import webbrowser
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PaaniTrayApp")

HUD_URL = "http://localhost:9120"
window_instance = None
overlay_visible = True

def create_tray_icon():
    """Generates a high-tech cyan/black PIL icon for the system tray."""
    img = Image.new("RGBA", (64, 64), color=(4, 6, 10, 255))
    draw = ImageDraw.Draw(img)
    # Draw outer neon cyan circle
    draw.ellipse([8, 8, 56, 56], outline=(0, 229, 255, 255), width=4)
    # Draw inner pulsing core
    draw.ellipse([24, 24, 40, 40], fill=(0, 230, 118, 255))
    return img

def toggle_overlay():
    global window_instance, overlay_visible
    logger.info("Toggling overlay window visibility...")
    if window_instance:
        try:
            if overlay_visible:
                window_instance.hide()
                overlay_visible = False
            else:
                window_instance.show()
                window_instance.restore()
                overlay_visible = True
        except Exception as e:
            logger.warning(f"Overlay window toggle exception: {e}")

def open_full_browser():
    webbrowser.open(HUD_URL)

def exit_app(icon=None, item=None):
    logger.info("Shutting down Paani 2.0 System Tray Companion...")
    if icon:
        icon.stop()
    os._exit(0)

def setup_global_hotkeys():
    """Listens for global hotkey Ctrl + Shift + Space to toggle HUD overlay."""
    try:
        import keyboard
        logger.info("Registering global hotkey 'Ctrl + Shift + Space'...")
        keyboard.add_hotkey("ctrl+shift+space", toggle_overlay)
    except Exception as e:
        logger.warning(f"Global hotkey listener notice: {e}. Overlay toggle active via tray menu.")

def run_pystray_icon():
    """Runs the system tray icon in a background thread."""
    try:
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("🌊 PAANI 2.0 HUD", lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚡ [Summon HUD Overlay] (Ctrl+Shift+Space)", lambda icon, item: toggle_overlay()),
            pystray.MenuItem("🌐 [Open Browser View (Full)]", lambda icon, item: open_full_browser()),
            pystray.MenuItem("⚙️ [Status: ONLINE]", lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ [Exit Paani 2.0]", exit_app)
        )
        icon = pystray.Icon("PaaniAI", create_tray_icon(), "PAANI 2.0 — Holographic Companion", menu)
        icon.run()
    except Exception as e:
        logger.warning(f"pystray tray icon fallback ({e}). Native webview active.")

def main():
    global window_instance
    logger.info("==================================================")
    logger.info("  🌊 PAANI 2.0 WINDOWS SYSTEM TRAY & OVERLAY APP")
    logger.info("==================================================")

    # Start tray icon thread
    tray_thread = threading.Thread(target=run_pystray_icon, daemon=True)
    tray_thread.start()

    # Start hotkey listener thread
    hotkey_thread = threading.Thread(target=setup_global_hotkeys, daemon=True)
    hotkey_thread.start()

    # Launch PyWebView frameless overlay window
    try:
        import webview
        logger.info(f"Launching PyWebView Frameless Overlay for {HUD_URL}...")
        window_instance = webview.create_window(
            title="PAANI 2.0 — Holographic Overlay",
            url=HUD_URL,
            width=1280,
            height=850,
            resizable=True,
            frameless=False, # Frameless HUD companion mode
            on_top=True,
            background_color="#04060a"
        )
        webview.start()
    except Exception as e:
        logger.warning(f"pywebview overlay window notice ({e}). Server active at {HUD_URL}.")
        open_full_browser()

if __name__ == "__main__":
    main()
