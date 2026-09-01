# 🌐 Brave Web AI Bridge (`brave-web-ai-bridge`)

> High-performance, lightweight WebSocket CDP bridge for AI Agents (Antigravity, Jules, AutoGPT) to coordinate and query Web AI chat interfaces running inside Brave Browser without opening redundant browser windows or burning API tokens.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## ✨ Supported Platforms & Model Selectors

| Platform | Target Flag | Supported Models | Key Features |
| :--- | :--- | :--- | :--- |
| **OKMD AI Playground** (`playground.okmd.or.th/chat`) | `--target okmd` | `deepseek`, `claude`, `gemini`, `openai`, `meta`, `perplexity`, `qwen`, `mistral`, `nova`, `xai`, `autorouter` | Dropdown model switching, `Reasoning (Pro)` / `Deep Research` toggle, `textarea.input-message` targeting |
| **AIPass Chat** (`de.aipass.net/chat`) | `--target aipass` | `Claude Opus 5`, `Claude Sonnet 5`, `Gemini 3.1 Pro`, `Gemini 3.7 Flash`, `GPT-5.6 Sol`, `DeepSeek V3.2` | Native setter + input event dispatch, model card auto-picker |
| **Microsoft 365 Copilot** (`m365.cloud.microsoft`) | `--target copilot` | GPT-4o Enterprise | Direct room/conversation binding via `--room <id>` |

---

## 🚀 Quick Start

### 1. Requirements
- Python 3.10+
- `websockets` & `requests`

```bash
pip install websockets requests
```

### 2. Launch Brave with Remote Debugging
Ensure Brave Browser is running with port 9222 enabled:
```powershell
"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222
```

### 3. Usage Examples

```bash
# Query OKMD using DeepSeek in Reasoning Mode:
python bridge.py ask --target okmd --model deepseek --msg-file "prompt.txt" --out-file "reply.md"

# Query AIPass using Claude Opus 5:
python bridge.py ask --target aipass --model "Claude Opus 5" --msg-file "prompt.txt" --out-file "reply.md"

# Query M365 Copilot in a specific room:
python bridge.py ask --target copilot --room "972aa5cd-beba-4ce8-ba65-4c7263ab3ff9" --msg-file "prompt.txt" --out-file "reply.md"
```

---

## 🛡️ Architecture & Design
- **Direct WebSocket CDP**: Avoids bulky Playwright/Selenium subprocesses that lock the browser debugger port.
- **Progressive Stream Capture**: Automatically tracks `document.body.innerText` length and detects completion once text stabilizes.
- **Fail-Safe Fallbacks**: Falls back to `KeyboardEvent` Enter dispatch if UI submit buttons are dynamic or hidden.

---

## 📜 License
MIT © 2026 [tukimtk-design](https://github.com/tukimtk-design)
