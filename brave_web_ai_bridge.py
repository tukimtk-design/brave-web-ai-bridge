"""
Brave Browser Universal Web AI Bridge CLI (Lightweight & High-Performance WebSocket CDP Edition)
Supports:
  - copilot : Microsoft 365 Copilot (m365.cloud.microsoft)
  - okmd    : OKMD AI Playground (playground.okmd.or.th/chat)
  - aipass  : AIPass Chat (de.aipass.net/chat)

Usage:
  python brave_web_ai_bridge.py ask --target okmd --model deepseek --msg-file "prompt.txt" --out-file "okmd_reply.md"
  python brave_web_ai_bridge.py ask --target aipass --model "Claude Opus 5" --msg-file "prompt.txt" --out-file "aipass_reply.md"
  python brave_web_ai_bridge.py ask --target aipass --task deep-reasoning --msg-file "prompt.txt" --out-file "aipass_reply.md"
  python brave_web_ai_bridge.py ask --target copilot --room "9a3189f1" --msg-file "prompt.txt" --out-file "copilot_reply.md"

Exit codes: 0 = response captured, 1 = connection/injection/response failure or timeout,
2 = aipass router exhausted every candidate model for the task class.
"""

import argparse
import asyncio
import json
import sys
import time

import requests
import websockets

from router.aipass_router import (
    TASK_ROUTING,
    apply_failure_cooldown,
    get_candidates_for_task,
    record_model_success,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CDP_CMD_TIMEOUT = 30  # seconds to wait for a single CDP command response
TAB_OPEN_WAIT = 4     # seconds to wait after opening a new browser tab
POLL_INTERVAL = 4     # seconds between response polling cycles
STABLE_CYCLES = 3     # consecutive stable polls before considering the response finished
MIN_RESPONSE_CHARS = 300


class BridgeError(RuntimeError):
    """Raised when a CDP command or in-page script fails."""


# Per-target configuration. Adding a new platform = adding one entry here
# plus an inject_script() branch (adapter split is planned for Phase 2).
TARGETS = {
    "copilot": {
        "url_match": "m365.cloud.microsoft",
        "home_url": "https://m365.cloud.microsoft/chat",
        "room_url_template": "https://m365.cloud.microsoft/chat/conversation/{room}",
        # Prefer the conversation panel; falls back to document.body
        "content_selectors": ["#m365-chat-main-panel", "main"],
    },
    "okmd": {
        "url_match": "okmd.or.th",
        "home_url": "https://playground.okmd.or.th/chat",
        "room_url_template": None,
        "content_selectors": ["div.chatbody", "main"],
    },
    "aipass": {
        "url_match": "aipass.net",
        "home_url": "https://de.aipass.net/chat",
        "room_url_template": None,
        "content_selectors": ["main"],
    },
}


class BraveCdpClient:
    def __init__(self, cdp_url="http://127.0.0.1:9222"):
        self.cdp_url = cdp_url
        self.ws = None
        self.req_id = 0
        self._pending = {}  # cmd id -> Future
        self._reader_task = None

    async def get_or_create_tab(self, target_type: str, room_identifier: str = ""):
        try:
            targets = requests.get(f"{self.cdp_url}/json", timeout=5).json()
        except Exception as e:
            print(f"[!] Error: Cannot connect to Brave on port 9222. Ensure Brave is running ({e})")
            sys.exit(1)

        cfg = TARGETS[target_type]

        # Match existing page tab (ignore iframes and service workers)
        matched_tab = None
        for t in targets:
            if t.get("type") != "page":
                continue
            url = t.get("url", "")
            title = t.get("title", "")

            if target_type == "copilot":
                if room_identifier and (room_identifier in url or room_identifier in title):
                    return t
                elif cfg["url_match"] in url:
                    matched_tab = t
            elif cfg["url_match"] in url:
                return t

        if matched_tab:
            # Room request but the open tab points elsewhere: the caller
            # navigates later over WebSocket (see execute_bridge), since the
            # HTTP endpoint cannot navigate an existing tab.
            return matched_tab

        # If not open, open new tab via the CDP HTTP endpoint (PUT is required
        # by newer Chrome/Brave versions).
        print(f"[INFO] Tab for {target_type} not open. Creating new tab via CDP...")
        if target_type == "copilot" and room_identifier:
            nav_url = room_identifier if room_identifier.startswith("http") else cfg["room_url_template"].format(room=room_identifier)
        else:
            nav_url = cfg["home_url"]

        new_tab = requests.put(f"{self.cdp_url}/json/new?{nav_url}", timeout=5).json()
        await asyncio.sleep(TAB_OPEN_WAIT)
        return new_tab

    def room_url(self, target_type: str, room_identifier: str) -> str:
        cfg = TARGETS[target_type]
        if room_identifier.startswith("http"):
            return room_identifier
        return cfg["room_url_template"].format(room=room_identifier) if cfg["room_url_template"] else cfg["home_url"]

    async def connect_ws(self, ws_url: str):
        self.ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024)
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        """Route incoming CDP messages: responses resolve pending futures."""
        try:
            async for raw in self.ws:
                try:
                    data = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                fut = self._pending.pop(data.get("id"), None)
                if fut and not fut.done():
                    fut.set_result(data)
        except Exception as e:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(e)
            self._pending.clear()

    async def send_cmd(self, method: str, params: dict | None = None):
        if self.ws is None:
            raise BridgeError("WebSocket not connected")
        self.req_id += 1
        curr_id = self.req_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[curr_id] = fut
        await self.ws.send(json.dumps({"id": curr_id, "method": method, "params": params or {}}))
        data = await asyncio.wait_for(fut, timeout=CDP_CMD_TIMEOUT)
        if "error" in data:
            raise BridgeError(f"CDP error from {method}: {data['error']}")
        return data.get("result", {})

    async def eval_js(self, expression: str):
        res = await self.send_cmd("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True
        })
        inner = res.get("result", {})
        if inner.get("exceptionDetails"):
            desc = inner["exceptionDetails"].get("exception", {}).get("description", "unknown JS error")
            raise BridgeError(f"In-page script failed: {desc}")
        return inner.get("value")

    async def press_enter(self):
        # Hardware key down and up via CDP (bypasses synthetic-event blocking)
        await self.send_cmd("Input.dispatchKeyEvent", {
            "type": "rawKeyDown",
            "windowsVirtualKeyCode": 13,
            "unmodifiedText": "\r",
            "text": "\r"
        })
        await self.send_cmd("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "windowsVirtualKeyCode": 13,
            "unmodifiedText": "\r",
            "text": "\r"
        })

    async def close(self):
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self.ws:
            await self.ws.close()
            self.ws = None


def build_inject_script(target: str, message: str, model: str) -> str:
    escaped_msg = json.dumps(message)
    escaped_model = json.dumps(model)

    if target == "okmd":
        return f"""
        (() => {{
            const targetModel = {escaped_model}.trim().toLowerCase();

            if (targetModel) {{
                const dropdownTriggers = Array.from(document.querySelectorAll('div.dropdown, div.icon.text-muted, [class*="dropdown-toggle"], button'));
                const trigger = dropdownTriggers.find(el => {{
                    const t = (el.innerText || '').toLowerCase();
                    return t.includes('auto router') || t.includes('auto select') || t.includes('model') || t.includes('openai') || t.includes('deepseek');
                }});
                if (trigger) trigger.click();

                setTimeout(() => {{
                    const modelItems = Array.from(document.querySelectorAll('a.dropdown-item-models, a.dropdown-item, li, button'));
                    const selected = modelItems.find(a => (a.innerText || '').toLowerCase().includes(targetModel));
                    if (selected) selected.click();
                }}, 300);
            }}

            const buttons = Array.from(document.querySelectorAll('button, div[role="button"]'));
            const reasoningBtn = buttons.find(b => {{
                const t = b.innerText || '';
                return t.includes('Reasoning (Pro)') || t.includes('Reasoning') || t.includes('Deep Research');
            }});
            if (reasoningBtn) reasoningBtn.click();

            const ta = document.querySelector('textarea.input-message') || document.querySelector('textarea:not([type="search"])') || document.querySelector('textarea');
            if (!ta) return {{ success: false, error: 'Cannot find textarea.input-message' }};

            ta.focus();
            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
            if (nativeSetter) nativeSetter.call(ta, {escaped_msg});
            else ta.value = {escaped_msg};
            ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
            ta.dispatchEvent(new Event('change', {{ bubbles: true }}));

            setTimeout(() => {{
                const sendBtn = document.querySelector('button.btn-sent-message') ||
                                Array.from(document.querySelectorAll('button')).find(b => b.querySelector('svg') && !b.innerText && b.type !== 'button') ||
                                document.querySelector('button[type="submit"]');
                if (sendBtn) sendBtn.click();
            }}, 600);

            return {{ success: true }};
        }})()
        """

    if target == "aipass":
        return f"""
        (() => {{
            const targetModel = ({escaped_model} || 'Claude Opus 5').trim().toLowerCase();

            const cards = Array.from(document.querySelectorAll('div, li, article, button'));
            const modelCard = cards.find(c => (c.innerText || '').toLowerCase().includes(targetModel));
            if (modelCard) {{
                const btn = modelCard.tagName === 'BUTTON' ? modelCard : modelCard.querySelector('button');
                if (btn) btn.click();
            }}

            const ta = document.querySelector('textarea');
            if (!ta) return {{ success: false, error: 'Cannot find textarea' }};

            ta.focus();
            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
            if (nativeSetter) nativeSetter.call(ta, {escaped_msg});
            else ta.value = {escaped_msg};
            ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
            ta.dispatchEvent(new Event('change', {{ bubbles: true }}));

            setTimeout(() => {{
                const allBtns = Array.from(document.querySelectorAll('button'));
                let sendBtn = allBtns.find(b => {{
                    const label = (b.getAttribute('aria-label') || '') + (b.innerText || '');
                    return label.includes('Send') || label.includes('ส่ง');
                }});
                if (!sendBtn) {{
                    sendBtn = allBtns.filter(b => b.offsetParent !== null && b.querySelector('svg')).pop();
                }}
                if (sendBtn) sendBtn.click();
            }}, 500);

            return {{ success: true }};
        }})()
        """

    # copilot
    return f"""
        (() => {{
            const inputEl = document.querySelector("#m365-chat-editor-target-element") ||
                            document.querySelector("span[aria-label*='Copilot'], span[aria-label*='ส่งข้อความ'], div[contenteditable='true'], [role='textbox']");
            if (!inputEl) return {{ success: false, error: 'Cannot find Copilot input box' }};

            inputEl.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('insertText', false, {escaped_msg});
            inputEl.dispatchEvent(new Event('input', {{ bubbles: true }}));

            let clicked = false;
            const submitBtn = document.querySelector("button.fai-SendButton") ||
                            document.querySelector("button[type='submit'][aria-label='ส่ง']") ||
                            document.querySelector("button[type='submit'][sendicon]") ||
                            document.querySelector("button[aria-label='ส่ง']") ||
                            Array.from(document.querySelectorAll('button')).find(b => {{
                                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                                return (aria.includes('ส่ง') || aria.includes('send')) && !b.disabled;
                            }});
            if (submitBtn) {{
                submitBtn.click();
                clicked = true;
            }}

            return {{ success: true, clickedBtn: clicked, targetTag: inputEl.tagName }};
        }})()
        """


def build_content_reader_script(target: str) -> str:
    """Read the response text. Copilot isolates the latest AI message
    (selectors from HANDOFF_TO_ZAI.md); other targets prefer the conversation
    panel and fall back to the whole body."""
    if target == "copilot":
        return """
        (() => {
            const aiMsgs = document.querySelectorAll(".fai-CopilotMessage__content, .fai-CopilotMessage, .fai-AiMessage, [data-content='ai-message'], [class*='AiResponse']");
            if (aiMsgs.length > 0) return aiMsgs[aiMsgs.length - 1].innerText;
            const el = document.querySelector("#m365-chat-main-panel, main");
            return (el || document.body).innerText;
        })()
        """
    selectors = TARGETS[target]["content_selectors"]
    selector_list = json.dumps(", ".join(selectors))
    return f"""
    (() => {{
        const el = document.querySelector({selector_list});
        return (el || document.body).innerText;
    }})()
    """

class AipassAdapter:
    """AIPass reliability layer, ported from aipass-auto-router Phase 2
    (Reliability Hardening). Uses the shared BraveCdpClient as transport —
    it never opens a browser itself (Zero-Browser Rule: CDP port 9222 only).

    Provides: model switch verification, send verification with retry,
    adaptive stream timeout, and wide error-toast detection.
    """

    SEND_RETRY_LIMIT = 2      # retries of the send step before declaring failure
    SEND_VERIFY_WAIT = 8      # seconds to confirm a send took effect
    STREAM_EXTEND_SECONDS = 30  # extend the deadline while still generating
    HARD_CAP_SECONDS = 600    # absolute max monitoring time even if still generating
    ADAPTER_POLL_INTERVAL = 1.5

    ASSISTANT_NODE_SELECTOR = ('div[class*="prose"], div[class*="markdown"], '
                               'div[class*="message"], [data-message-author-role="assistant"]')

    ERROR_KEYWORDS = ["limit", "quota", "failed", "error", "unauthorized", "expired",
                      "try again", "เกิดข้อผิดพลาด", "ลองอีกครั้ง"]

    def __init__(self, client: BraveCdpClient):
        self.client = client

    async def _eval(self, expression: str):
        return await self.client.eval_js(expression)

    async def select_model(self, target_model: str) -> bool:
        """Click the model dropdown and verify the button label actually switched
        (aipass model buttons use class bg-bg-input-control)."""
        escaped_model = json.dumps(target_model)
        open_js = f"""
        (() => {{
            const target = {escaped_model}.toLowerCase();
            const modelBtn = Array.from(document.querySelectorAll('button')).find(b => {{
                const txt = (b.innerText || '').toLowerCase();
                return (txt.includes('claude') || txt.includes('gpt') || txt.includes('gemini') || txt.includes('deepseek') || txt.includes('sonnet') || txt.includes('opus')) && b.className.includes('bg-bg-input-control');
            }});
            if (!modelBtn) return {{ success: false, reason: 'model_button_not_found' }};
            if (modelBtn.innerText.toLowerCase().includes(target)) {{
                return {{ success: true, alreadySelected: true }};
            }}
            modelBtn.click();
            return {{ success: true, opened: true }};
        }})()
        """
        res = await self._eval(open_js)
        if not res or not res.get("success"):
            return False
        if res.get("alreadySelected"):
            return True

        await asyncio.sleep(0.6)
        pick_js = f"""
        (() => {{
            const target = {escaped_model}.toLowerCase();
            const items = Array.from(document.querySelectorAll('[role="menuitem"], [role="option"], button, div[class*="item"], div[class*="card"]'));
            const match = items.find(el => {{
                const txt = (el.innerText || '').toLowerCase();
                return txt.includes(target) && el.offsetParent !== null;
            }});
            if (match) {{ match.click(); return {{ success: true }}; }}
            return {{ success: false, reason: 'item_not_found' }};
        }})()
        """
        res_pick = await self._eval(pick_js)
        await asyncio.sleep(0.5)
        if not res_pick or not res_pick.get("success"):
            return False

        # Verify the button label actually switched to the target model.
        verify_js = f"""
        (() => {{
            const target = {escaped_model}.toLowerCase();
            const modelBtn = Array.from(document.querySelectorAll('button')).find(b => {{
                const txt = (b.innerText || '').toLowerCase();
                return (txt.includes('claude') || txt.includes('gpt') || txt.includes('gemini') || txt.includes('deepseek') || txt.includes('sonnet') || txt.includes('opus')) && b.className.includes('bg-bg-input-control');
            }});
            return modelBtn ? modelBtn.innerText.toLowerCase().includes(target) : false;
        }})()
        """
        return bool(await self._eval(verify_js))

    async def count_assistant_messages(self) -> int:
        val = await self._eval(f"""
        (() => {{
            return document.querySelectorAll('{self.ASSISTANT_NODE_SELECTOR}').length;
        }})()
        """)
        return int(val) if isinstance(val, (int, float)) else 0

    async def inject_prompt(self, prompt_text: str) -> dict:
        """Inject the prompt into the textarea via the React native value setter."""
        escaped_prompt = json.dumps(prompt_text)
        return await self._eval(f"""
        (() => {{
            const prompt = {escaped_prompt};
            const textarea = document.querySelector('textarea');
            if (!textarea) return {{ success: false, error: 'textarea_not_found' }};
            textarea.focus();
            const proto = window.HTMLTextAreaElement.prototype;
            const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            nativeSetter.call(textarea, prompt);
            textarea.dispatchEvent(new Event('input', {{ bubbles: true, cancelable: true }}));
            textarea.dispatchEvent(new Event('change', {{ bubbles: true, cancelable: true }}));
            const echoOk = textarea.value === prompt;
            return {{ success: true, echoOk }};
        }})()
        """) or {"success": False, "error": "no_result"}

    async def trigger_send(self) -> str:
        """Click the send button if present, otherwise fall back to a CDP
        hardware Enter key (Input.dispatchKeyEvent, virtual key 13)."""
        method = await self._eval("""
        (() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const sendBtn = buttons.find(b => {
                const txt = (b.innerText || '').toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                const isSend = txt.includes('send') || aria.includes('send') || b.className.includes('bg-bg-brand-primary');
                return isSend && !b.disabled && b.offsetParent !== null;
            });
            if (sendBtn) { sendBtn.click(); return 'button'; }
            return 'none';
        })()
        """)
        if method == "button":
            return "button"
        await self.client.press_enter()
        return "enter"

    async def verify_send(self, baseline_count: int, wait_seconds: float = None) -> bool:
        """A send is verified when the assistant message count grows beyond the
        baseline (or the textarea was cleared) within a short window."""
        wait = wait_seconds if wait_seconds is not None else self.SEND_VERIFY_WAIT
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            data = await self._eval(f"""
            (() => {{
                const nodes = document.querySelectorAll('{self.ASSISTANT_NODE_SELECTOR}');
                const textarea = document.querySelector('textarea');
                return {{ count: nodes.length, cleared: textarea ? textarea.value.length === 0 : true }};
            }})()
            """) or {}
            if int(data.get("count", 0)) > baseline_count:
                return True
            await asyncio.sleep(self.ADAPTER_POLL_INTERVAL)
        return False

    async def send_and_verify(self, prompt_text: str) -> bool:
        """Inject + send with verification, retrying up to SEND_RETRY_LIMIT."""
        baseline = await self.count_assistant_messages()
        for attempt in range(1, self.SEND_RETRY_LIMIT + 1):
            inject_res = await self.inject_prompt(prompt_text)
            if not inject_res.get("success"):
                print(f"[WARN] Inject failed (attempt {attempt}): {inject_res}", flush=True)
                await asyncio.sleep(1)
                continue
            await self.trigger_send()
            if await self.verify_send(baseline):
                return True
            print(f"[WARN] Send not verified (attempt {attempt}) — retrying", flush=True)
            await asyncio.sleep(1)
        return False

    async def monitor_response(self, timeout_seconds: int = 150) -> str:
        """Monitor the newest assistant message until finalized.

        The deadline extends by STREAM_EXTEND_SECONDS whenever the UI still
        reports an active generation (stop button visible), bounded by
        HARD_CAP_SECONDS overall — reasoning models answering at length must
        not be cut off mid-stream by a fixed timeout.
        """
        start = time.monotonic()
        deadline = start + timeout_seconds
        last_text = ""
        stable_count = 0

        extract_js = f"""
        (() => {{
            const errorToast = document.querySelector('[role="alert"], [class*="toast"], [class*="error"]');
            const errorMsg = errorToast ? errorToast.innerText : null;
            const nodes = Array.from(document.querySelectorAll('{self.ASSISTANT_NODE_SELECTOR}'));
            let assistantText = "";
            if (nodes.length > 0) {{
                assistantText = nodes[nodes.length - 1].innerText;
            }}
            const stopBtn = Array.from(document.querySelectorAll('button')).find(b => {{
                const txt = (b.innerText || '').toLowerCase();
                return txt.includes('stop') || txt.includes('หยุด');
            }});
            return {{
                text: assistantText,
                isGenerating: stopBtn !== undefined && stopBtn !== null,
                hasError: errorMsg !== null,
                error: errorMsg
            }};
        }})()
        """

        while True:
            now = time.monotonic()
            if now > deadline or now - start >= self.HARD_CAP_SECONDS:
                print(f"[WARN] Monitor deadline reached ({round(now - start, 1)}s elapsed)", flush=True)
                return last_text

            data = await self._eval(extract_js)
            if not data:
                await asyncio.sleep(self.ADAPTER_POLL_INTERVAL)
                continue

            error_text = data.get("error") or ""
            lowered = error_text.lower()
            if data.get("hasError") and any(k in lowered for k in self.ERROR_KEYWORDS):
                raise BridgeError(f"MODEL_ERROR: {error_text}")

            current_text = data.get("text", "") or ""
            is_generating = data.get("isGenerating", False)

            if is_generating:
                deadline = min(deadline + self.STREAM_EXTEND_SECONDS, start + self.HARD_CAP_SECONDS)

            if current_text and current_text == last_text and not is_generating:
                stable_count += 1
                if stable_count >= STABLE_CYCLES:
                    return current_text
            else:
                stable_count = 0
                last_text = current_text

            await asyncio.sleep(self.ADAPTER_POLL_INTERVAL)

    async def attempt_with_model(self, model: str, prompt_text: str, timeout_seconds: int = 150) -> str:
        """Select the model, send with verification, monitor the stream.
        Raises BridgeError tagged MODEL_ERROR / SEND_FAILED / MODEL_SWITCH_FAILED
        so the failover loop can apply the right cooldown."""
        if not await self.select_model(model):
            raise BridgeError(f"MODEL_SWITCH_FAILED: could not select '{model}'")
        print(f"[MODEL] Model '{model}' selected and verified.", flush=True)

        if not await self.send_and_verify(prompt_text):
            raise BridgeError(f"SEND_FAILED: message send could not be verified for '{model}'")
        print("[SEND] Message send verified.", flush=True)

        response = await self.monitor_response(timeout_seconds=timeout_seconds)
        if not response.strip():
            raise BridgeError(f"MODEL_ERROR: empty response from '{model}'")
        return response


async def execute_aipass_routed(client: BraveCdpClient, task_class: str, message: str,
                                out_file: str, timeout_sec: int) -> bool:
    """Failover loop across the cooldown-aware candidate list for a task class.
    Returns True on success; False when every candidate was exhausted
    (the CLI maps that to exit code 2)."""
    adapter = AipassAdapter(client)
    candidates = get_candidates_for_task(task_class)
    print(f"[ROUTER] Task class: '{task_class}' -> Candidate order: {candidates}", flush=True)

    last_error = None
    for idx, model in enumerate(candidates):
        print(f"[ATTEMPT {idx + 1}/{len(candidates)}] Trying model '{model}'", flush=True)
        try:
            started = time.monotonic()
            full_response = await adapter.attempt_with_model(model, message, timeout_seconds=timeout_sec)
            elapsed = round(time.monotonic() - started, 1)
            record_model_success(model, elapsed)
            print(f"[SUCCESS] Generation complete via '{model}' in {elapsed}s. Length: {len(full_response)} chars.", flush=True)
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(full_response)
            print(f"[OK] Successfully saved response to {out_file}", flush=True)
            return True
        except (BridgeError, asyncio.TimeoutError) as err:
            last_error = str(err)
            print(f"[FAILOVER] Model '{model}' failed: {err}", flush=True)
            apply_failure_cooldown(last_error, model)
            print("[FAILOVER] Moving to next candidate...", flush=True)
            await asyncio.sleep(1)

    print(f"[FATAL] All candidate models exhausted. Last error: {last_error}", flush=True)
    return False


async def execute_bridge(target: str, message: str, out_file: str, model: str = "", room_id: str = "", timeout_sec: int = 240, task_class: str = "", new_session: bool = False) -> bool:
    client = BraveCdpClient()
    tab = await client.get_or_create_tab(target, room_id)
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        print(f"[!] No webSocketDebuggerUrl found for tab: {tab}")
        sys.exit(1)

    print(f"[OK] Connecting via WebSocket CDP to [{target.upper()}]: {tab.get('title')}", flush=True)
    await client.connect_ws(ws_url)

    # AIPass router mode: --task without --model selects the model via
    # TASK_ROUTING and fails over the candidate list (exit code 2 on exhaustion).
    if target == "aipass" and task_class and not model:
        ok = await execute_aipass_routed(client, task_class, message, out_file, timeout_sec)
        await client.close()
        return ok

    # Navigate an existing tab to the requested room if it points elsewhere
    if target == "copilot" and room_id and room_id not in tab.get("url", ""):
        room_url = client.room_url(target, room_id)
        print(f"[INFO] Navigating existing Copilot tab to room: {room_url}")
        await client.send_cmd("Page.navigate", {"url": room_url})
        await asyncio.sleep(3)

    # Bring tab to front
    await client.send_cmd("Page.bringToFront")
    await asyncio.sleep(0.5)

    print(f"[1] Injecting prompt into [{target.upper()}]" + (f" (model '{model}')" if model else "") + "...", flush=True)
    res = await client.eval_js(build_inject_script(target, message, model))
    print(f"[2] Injection result: {res}", flush=True)
    if not res or not res.get("success"):
        error = (res or {}).get("error", "in-page script returned no result")
        print(f"[!] Injection failed: {error}")
        await client.close()
        return False

    if target == "copilot":
        await asyncio.sleep(0.5)
        await client.eval_js("""
        (() => {
            const btn = document.querySelector("button.fai-SendButton") ||
                        document.querySelector("button[aria-label='Send']") ||
                        document.querySelector("button[aria-label*='ส่ง']");
            if (btn && !btn.disabled) btn.click();
        })()
        """)
        await client.press_enter()

    print(f"[3] Prompt sent to [{target.upper()}]. Monitoring response...", flush=True)

    content_script = build_content_reader_script(target)
    prev_len = 0
    stable_count = 0
    start = time.time()
    snippet = message[:35].strip()
    finished = False

    while time.time() - start < timeout_sec:
        await asyncio.sleep(POLL_INTERVAL)

        await client.eval_js("""
        (() => {
            const scrollBtn = document.querySelector("button[aria-label*='เลื่อน'], button[aria-label*='Scroll']");
            if (scrollBtn) scrollBtn.click();
            window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
        })()
        """)

        text = await client.eval_js(content_script) or ""

        # Copilot reads the isolated AI message, so trimming the prompt
        # snippet off the front is neither needed nor safe
        if snippet and target != "copilot":
            idx = text.rfind(snippet)
            if idx != -1:
                text = text[idx:]

        cur_len = len(text)
        print(f"  Streaming {target} response: {cur_len} chars...", flush=True)

        if cur_len > MIN_RESPONSE_CHARS and cur_len == prev_len:
            stable_count += 1
            if stable_count >= STABLE_CYCLES:
                print(f"\n[OK] {target.upper()} response finished & stabilized ({cur_len} chars)!", flush=True)
                with open(out_file, "w", encoding="utf-8") as f:
                    f.write(text)
                print(f"[OK] Successfully saved response to {out_file}")
                finished = True
                break
        else:
            stable_count = 0
            prev_len = cur_len

    if not finished:
        print(f"[!] Timeout after {timeout_sec}s: response did not stabilize. No output written to {out_file}")

    await client.close()
    return finished


def main():
    parser = argparse.ArgumentParser(description="Universal Brave Web AI Bridge CLI (WebSocket CDP)")
    parser.add_argument("action", choices=["ask", "send", "read"])
    parser.add_argument("--target", choices=list(TARGETS), default="copilot", help="Target Web AI platform")
    parser.add_argument("--model", default="", help="Specific AI Model to select (e.g. deepseek, claude, gemini, openai)")
    parser.add_argument("--task", default="", choices=[""] + list(TASK_ROUTING), help="Task class for aipass router mode (model chosen + failover); ignored when --model is given")
    parser.add_argument("--room", default="", help="Room URL or conversation ID (for Copilot)")
    parser.add_argument("--msg-file", required=True, help="Path to prompt file")
    parser.add_argument("--out-file", default="ai_response.md", help="Path to save reply")
    parser.add_argument("--timeout", type=int, default=240, help="Max timeout in seconds")

    args = parser.parse_args()

    with open(args.msg_file, "r", encoding="utf-8") as f:
        msg = f.read()

    ok = asyncio.run(execute_bridge(args.target, msg, args.out_file, model=args.model, room_id=args.room, timeout_sec=args.timeout, task_class=args.task))
    if not ok:
        # Exit code 2 = aipass router exhausted every candidate model
        sys.exit(2 if (args.target == "aipass" and args.task and not args.model) else 1)


if __name__ == "__main__":
    main()
