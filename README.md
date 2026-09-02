# Brave Web AI Bridge CLI (Universal WebSocket CDP Edition)

A high-performance, lightweight Python CLI tool to connect to and coordinate with Web AI interfaces (**Microsoft 365 Copilot**, **OKMD AI Playground**, and **AIPass Chat**) running inside a user's active **Brave Browser** session via Chrome DevTools Protocol (**WebSocket CDP on port 9222**).

---

## 🌟 Key Features

- ⚡ **Zero Browser Launch Overhead:** Connects to your existing, logged-in Brave Browser session on port 9222 without opening duplicate windows or triggering security captchas.
- 🎯 **Full Microsoft 365 Copilot Enterprise Support:** Native handling for Lexical/Draft.js rich-text editors (`#m365-chat-editor-target-element`), `document.execCommand('insertText')` DOM state synchronization, and Thai localization (`ส่ง`, `ส่งข้อความ`).
- 🤖 **OKMD AI Playground Support:** DeepSeek V3/Reasoning Pro, Anthropic Claude, OpenAI GPT, Google Gemini, Qwen, Mistral.
- 💬 **AIPass Chat Support:** Claude Opus 5, Claude Sonnet 5, Gemini 3.1 Pro, GPT-5.6 Sol.
- ⌨️ **CDP Hardware Key Injection:** Bypasses synthetic event blocking via `Input.dispatchKeyEvent` (Virtual KeyCode 13).
- 📜 **Auto-Viewport Scroll:** Detects and triggers floating scroll-to-bottom buttons automatically to ensure response streaming and rendering.

---

## 🚀 Quick Usage Syntax

```bash
# 1. Query M365 Copilot (Specific Conversation Room):
python brave_web_ai_bridge.py ask --target copilot --room "9a3189f1-f8ed-477f-97ae-97f8f3a72d5c" --msg-file "prompt.txt" --out-file "reply.md"

# 2. Query OKMD DeepSeek in Reasoning Mode:
python brave_web_ai_bridge.py ask --target okmd --model deepseek --msg-file "prompt.txt" --out-file "reply.md"

# 3. Query AIPass Claude Opus 5:
python brave_web_ai_bridge.py ask --target aipass --model "Claude Opus 5" --msg-file "prompt.txt" --out-file "reply.md"
```

---

## 🛠️ Requirements & Setup

- **Python 3.10+**
- `pip install websockets requests`
- **Brave Browser** running with remote debugging port enabled:
  ```powershell
  & "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222
  ```

---

## 📄 License
MIT License
