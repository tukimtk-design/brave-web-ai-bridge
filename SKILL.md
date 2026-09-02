---
name: brave-web-ai-bridge
description: >-
  Connect to and coordinate with Web AI interfaces (OKMD AI Playground, AIPass Chat,
  and Microsoft 365 Copilot) running inside Brave Browser via Chrome DevTools Protocol
  (WebSocket CDP on port 9222). Use to brainstorm, query external frontier models
  (Claude Opus 5, DeepSeek, GPT-5, Gemini Pro) without opening duplicate browser windows.
---

# Brave Web AI Bridge Skill

This skill allows Antigravity and subagents to interact with Web AI Chat systems running inside a user-logged-in Brave Browser session on port 9222.

## Available Targets & Capabilities

### 1. OKMD AI Playground (`playground.okmd.or.th/chat`)
- **CLI Target:** `--target okmd`
- **Supported Models via `--model <name>`:**
  - `deepseek` : DeepSeek V3 / Reasoning
  - `claude`   : Anthropic Claude
  - `openai`   : OpenAI GPT models
  - `gemini`   : Google Gemini
  - `meta`     : Meta Llama
  - `perplexity`: Perplexity Sonar
  - `qwen`     : Alibaba Qwen
  - `mistral`  : Mistral AI
  - `autorouter`: Auto Select Model
- **Key Selectors:**
  - Input: `textarea.input-message`
  - Submit: `button.btn-sent-message`
  - Model Dropdown: `div.icon.text-muted` -> `a.dropdown-item-models`

### 2. AIPass Chat (`de.aipass.net/chat`)
- **CLI Target:** `--target aipass`
- **Supported Models via `--model <name>`:**
  - `Claude Opus 5` (Default for high-level architectural brainstorming)
  - `Claude Sonnet 5`
  - `Gemini 3.1 Pro`
  - `GPT-5.6 Sol`
- **Key Selectors:**
  - Input: `textarea` (dispatches `input` event with `{ bubbles: true }`)
  - Submit: `button[aria-label*="Send"]` or form submit

### 3. Microsoft 365 Copilot (`m365.cloud.microsoft`)
- **CLI Target:** `--target copilot --room "<room-id-or-url>"`
- **Capability:** Queries internal enterprise Copilot chat room directly.
- **Key Selectors & DOM Specifics:**
  - **Editor Element:** `#m365-chat-editor-target-element` (or `span[role='textbox'][contenteditable='true']`).
  - **Crucial Rule:** Copilot uses a Lexical/Draft.js rich-text editor. Setting `.innerText` or `.value` directly **fails silently** (internal React state remains empty, and the send button stays disabled).
  - **Required Text Injection Method:**
    ```javascript
    const editor = document.querySelector("#m365-chat-editor-target-element") || document.querySelector("span[role='textbox'][contenteditable='true']");
    editor.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, text);
    editor.dispatchEvent(new Event('input', { bubbles: true }));
    ```
  - **Submit Button:** In English UI it has `aria-label="Send"` or `"Submit"`. In Thai UI it has `aria-label="ส่ง"` or `aria-label="ส่งข้อความ"`.
  - **Hardware Enter Key:** Modern Chromium blocks synthetic `isTrusted=false` key events. Must dispatch hardware key event via CDP:
    `Input.dispatchKeyEvent` with `type: 'rawKeyDown'`, `windowsVirtualKeyCode: 13`.
  - **Viewport Auto-Scroll:** Long responses trigger a floating scroll-to-bottom button (`button[aria-label*='เลื่อน']` / `button[aria-label*='Scroll']`). The bridge script automatically clicks it and scrolls to ensure text is rendered.

---

## Execution Command Syntax

```bash
# Query OKMD DeepSeek in Reasoning Mode:
python C:/Users/Kim/.gemini/scripts/brave_web_ai_bridge.py ask --target okmd --model deepseek --msg-file "prompt.txt" --out-file "reply.md"

# Query AIPass Claude Opus 5:
python C:/Users/Kim/.gemini/scripts/brave_web_ai_bridge.py ask --target aipass --model "Claude Opus 5" --msg-file "prompt.txt" --out-file "reply.md"

# Query M365 Copilot Specific Room:
python C:/Users/Kim/.gemini/scripts/brave_web_ai_bridge.py ask --target copilot --room "9a3189f1-f8ed-477f-97ae-97f8f3a72d5c" --msg-file "prompt.txt" --out-file "reply.md"
```

---

## Troubleshooting & Pitfalls Avoidance for Agents
1. **Never launch a new Chrome or Brave window** if Brave is already open on port 9222.
2. **Tab Filtering:** Always filter `t.type === 'page'` when inspecting `http://127.0.0.1:9222/json`. M365 tabs include OAuth iframes (`login.live.com`, `login.microsoftonline.com`) which will error if targeted.
3. **Multi-turn Context Saturation:** If Copilot displays `"Please type a message to continue"` or reaches room turn limits, navigate the tab to `https://m365.cloud.microsoft/chat` to start a clean session with full token headroom.
4. **Direct WebSocket CDP vs Selenium/Playwright:** Always use direct WebSocket connection (`ws://127.0.0.1:9222/devtools/page/<ID>`) rather than `playwright.connect_over_cdp()`. Playwright scans all open background tabs sequentially and hangs on cookie-rotation tabs.

