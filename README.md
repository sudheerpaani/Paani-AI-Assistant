# Paani V0.3 - Windows Background AI Assistant 🌊

Paani is a **local-first Windows background AI assistant** powered by your local [Ollama](https://ollama.com) installation (default model: `llama3.2:3b`).

Rather than being a traditional web chat application, Paani runs silently in the Windows background system tray and activates whenever you press **`Ctrl + Space`** (or say *"Hey Paani"*), displaying a floating assistant overlay on your screen.

---

## 🏗️ Paani V0.3 Architecture Overview

```
Paani AI assistant/
├── main.js                        # Background process lifecycle, Tray, Overlay & IPC router
├── preload.js                     # Secure bridge between UI renderer windows and backend process
├── launch.ps1                     # Desktop launcher script
├── package.json                   # Dependency runner
│
└── src/
    ├── core/
    │   ├── stateManager.js        # 🟢 Single source of truth for Connection & Assistant states
    │   └── assistantCore.js       # 🧠 Central coordinator handling prompt routing & response streaming
    │
    ├── tray/
    │   └── systemTray.js          # 📌 Windows System Tray icon, tooltips, and context menu
    │
    ├── overlay/
    │   ├── assistantOverlay.js    # 🪟 Floating overlay window manager
    │   ├── overlay.html           # Overlay visual states (IDLE, LISTENING, THINKING, SPEAKING)
    │   ├── overlay.css            # Glassmorphic dark theme styles & animations
    │   └── overlayApp.js          # Overlay UI controller
    │
    ├── voice/
    │   ├── wakeWord/
    │   │   └── wakeWordEngine.js  # 🎙️ Wake-word interface with Ctrl+Space hotkey fallback
    │   ├── speechToText/
    │   │   └── sttEngine.js       # 🗣️ Modular Speech-to-Text abstraction
    │   └── textToSpeech/
    │       └── ttsEngine.js       # 🔊 Modular Text-to-Speech abstraction
    │
    ├── llm/
    │   └── ollamaClient.js        # 🤖 Handles local Ollama API streaming & model tags
    │
    ├── conversation/
    │   └── conversationManager.js # 💬 Unified session history & local storage (paani_chats.json)
    │
    ├── config/
    │   └── configManager.js       # ⚙️ Settings persistence (paani_config.json)
    │
    ├── tools/
    │   └── toolRegistry.js        # 🔧 Modular plugin interface stub for future tool expansions
    │
    └── ui/                        # 🎨 Secondary Developer & Conversation Interface
        ├── index.html
        ├── styles.css
        └── app.js
```

---

## 🧩 Key V0.3 Components & Responsibilities

### 1. `src/core/stateManager.js` (Unified State Engine)
- **Role**: Single source of truth.
- **Connection States**: `CHECKING`, `CONNECTED`, `DISCONNECTED`, `ERROR`.
- **Assistant States**: `IDLE`, `LISTENING`, `THINKING`, `WORKING`, `SPEAKING`.
- Prevents status message mismatches across Tray, Dev Chat, and Overlay.

### 2. `src/core/assistantCore.js` (Assistant Coordinator)
- **Role**: Central brain routing text or voice inputs.
- Orchestrates multi-turn Ollama LLM requests, streams tokens live, and saves conversations to `conversationManager`.

### 3. `src/tray/systemTray.js` (Windows System Tray Integration)
- **Role**: Quiet background presence in the Windows taskbar tray.
- Provides status tooltips (e.g. `● Paani Ready`, `🎙 Listening`, `🧠 Thinking`, `🔊 Speaking`) and a right-click menu to toggle Overlay, open Dev Chat UI, or quit.

### 4. `src/overlay/` (Floating Assistant Overlay)
- **Role**: Primary mini visual interface.
- Frameless, floating, always-on-top window positioned in the bottom-right corner of the screen. Supports dynamic state cards (`IDLE`, `LISTENING`, `THINKING`, `WORKING`, `SPEAKING`) and push-to-talk.

### 5. `src/voice/` (Modular Voice Pipeline)
- **`wakeWordEngine.js`**: Extensible wake-word interface with a global **`Ctrl + Space`** hotkey fallback for instant development activation.
- **`sttEngine.js`**: Modular Speech-to-Text abstraction.
- **`ttsEngine.js`**: Modular Text-to-Speech abstraction.

---

## 🚀 How to Run Paani V0.3

1. Make sure **Ollama** is running locally:
   ```bash
   ollama run llama3.2:3b
   ```
2. Start Paani:
   ```powershell
   npm start
   ```
3. Press **`Ctrl + Space`** anywhere in Windows to summon the **Paani Overlay**!
4. Closing the main Dev Chat window minimizes Paani to the **System Tray** without quitting the background assistant.

---

## 🔒 Local-First Privacy Guarantee
All conversations, voice pipelines, and configuration settings are processed strictly on your machine. Zero external API calls.
