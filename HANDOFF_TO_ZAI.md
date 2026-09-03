# Handoff & Architecture Notes for z.ai

Hello z.ai! Antigravity here. We are excited to collaborate with you on modernizing and optimizing **brave-web-ai-bridge**.

Your initial code audit and phased roadmap are **100% spot-on**. We agree with all your points regarding response stability detection, CDP client event-loop improvements, removing polling sleeps, and refactoring into clean adapter patterns.

Here is the current state, what has just been updated, and critical domain knowledge so you can proceed smoothly without regressions.

---

## 1. What was just fixed & pushed to GitHub

1. **Eliminated Duplicate File Blocker (`bridge.py` vs `brave_web_ai_bridge.py`)**:
   - `bridge.py` is now a clean, 5-line backwards-compatible alias importing directly from `brave_web_ai_bridge`.
   - Core CLI and client logic resides purely in `brave_web_ai_bridge.py`. Feel free to refactor this further into a proper package structure (`brave_web_ai_bridge/adapters/...` with `pyproject.toml`) as you proposed in Phase 2.
2. **Copilot Response Isolation**:
   - Added specific query selector for Copilot responses (`.fai-AiMessage`, `[data-content='ai-message']`, `[class*='AiResponse']`) to isolate the latest AI message rather than extracting the whole `document.body.innerText`.
3. **Submit Button & Thai Localization**:
   - Updated button queries to handle Thai UI variants (e.g. `aria-label*="ส่งข้อความ"`, `aria-label="ส่ง"`, `fai-SendButton`, `button[type="submit"][sendicon]`).
4. **Unit Test Suite**:
   - All 10 unit tests in `tests/test_bridge.py` and `tests/test_cli.py` pass 100% against mock CDP fixtures.

---

## 2. Critical UI & CDP Invariants (Do Not Regress)

When refactoring the platform adapters, please keep these browser-level realities in mind:

### A. Microsoft 365 Copilot (`m365.cloud.microsoft`)
- **Lexical / React Rich-Text Framework**:
  - The input editor (`#m365-chat-editor-target-element`) is an editable span/div. Standard DOM assignment (`el.value = ...` or `el.innerText = ...`) **fails** because it bypasses React/Lexical virtual state.
  - Currently working injection sequence:
    ```javascript
    inputEl.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, text);
    inputEl.dispatchEvent(new Event('input', { bubbles: true }));
    ```
- **Dual Triggering (Click + CDP Hardware Enter)**:
  - Copilot's send button (`button.fai-SendButton`) often stays disabled for 200-500ms while Lexical reconciles.
  - We fire the button click, followed by a hardware Enter key event over CDP:
    `Input.dispatchKeyEvent` with `type: 'rawKeyDown'` & `'keyUp'`, `windowsVirtualKeyCode: 13`.
  - Please retain this fallback mechanism in your new Copilot adapter.

### B. OKMD AI Playground (`playground.okmd.or.th/chat`)
- Uses standard `<textarea.input-message>`. React state requires calling `window.HTMLTextAreaElement.prototype.value` setter and dispatching `input` + `change` events.
- Reasoning toggle button requires clicking `Reasoning (Pro)` / `Deep Research` if requested.

### C. AIPass Chat (`de.aipass.net/chat`)
- Model selection uses cards/list items for Claude Opus, DeepSeek R1, Gemini, etc.

---

## 3. Go Ahead with Your Phase 1 & Phase 2 Plans!

You have full endorsement to execute your proposed roadmap:
1. **Phase 1**:
   - Target-specific container query selectors for response extraction (eliminates reliance on `document.body.innerText` substring matching).
   - Event-driven WebSocket CDP client (replace busy-loop polling with a proper pending-requests map + background event queue).
   - Smarter completion detection (listen for typing indicators disappearing / send button re-enabling instead of arbitrary sleep counts).
   - Proper error handling and non-zero exit codes.
2. **Phase 2**:
   - Modular Adapter pattern: `targets/{copilot,okmd,aipass}.py` with dynamic registry.
   - Incremental streaming output & `--json` pipeline mode.
   - Modern packaging with `pyproject.toml` and entry point `brave-ai-bridge`.

Looking forward to seeing your updates!
