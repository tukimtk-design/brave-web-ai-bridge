"""
Brave Browser Universal Web AI Bridge CLI (Lightweight & High-Performance WebSocket CDP Edition)
Supports:
  - copilot : Microsoft 365 Copilot (m365.cloud.microsoft)
  - okmd    : OKMD AI Playground (playground.okmd.or.th/chat)
  - aipass  : AIPass Chat (de.aipass.net/chat)

Usage:
  python brave_web_ai_bridge.py ask --target okmd --model deepseek --msg-file "prompt.txt" --out-file "okmd_reply.md"
  python brave_web_ai_bridge.py ask --target aipass --model "Claude Opus 5" --msg-file "prompt.txt" --out-file "aipass_reply.md"
  python brave_web_ai_bridge.py ask --target copilot --room "9a3189f1" --msg-file "prompt.txt" --out-file "copilot_reply.md"

Exit codes: 0 = response captured, 1 = connection/injection/response failure or timeout.
"""

import argparse
import asyncio
import json
import sys
import time
import requests
import websockets

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

    async def send_cmd(self, method: str, params: dict = None):
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
            const aiMsgs = document.querySelectorAll(".fai-AiMessage, [data-content='ai-message'], [class*='AiResponse']");
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


async def execute_bridge(target: str, message: str, out_file: str, model: str = "", room_id: str = "", timeout_sec: int = 240) -> bool:
    client = BraveCdpClient()
    tab = await client.get_or_create_tab(target, room_id)
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        print(f"[!] No webSocketDebuggerUrl found for tab: {tab}")
        sys.exit(1)

    print(f"[OK] Connecting via WebSocket CDP to [{target.upper()}]: {tab.get('title')}", flush=True)
    await client.connect_ws(ws_url)

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
    parser.add_argument("--room", default="", help="Room URL or conversation ID (for Copilot)")
    parser.add_argument("--msg-file", required=True, help="Path to prompt file")
    parser.add_argument("--out-file", default="ai_response.md", help="Path to save reply")
    parser.add_argument("--timeout", type=int, default=240, help="Max timeout in seconds")

    args = parser.parse_args()

    with open(args.msg_file, "r", encoding="utf-8") as f:
        msg = f.read()

    ok = asyncio.run(execute_bridge(args.target, msg, args.out_file, model=args.model, room_id=args.room, timeout_sec=args.timeout))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
