"""
Brave Web AI Bridge
Universal Chrome DevTools Protocol (CDP) WebSocket Bridge for AI Agents
Supports:
  - OKMD AI Playground (playground.okmd.or.th/chat) with Multi-Model Dropdown Selection
  - AIPass Chat (de.aipass.net/chat) with Multi-Model Selection (Claude Opus 5, Sonnet, Gemini, GPT)
  - Microsoft 365 Copilot (m365.cloud.microsoft)
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


class BraveCdpClient:
    def __init__(self, cdp_url="http://127.0.0.1:9222"):
        self.cdp_url = cdp_url
        self.ws = None
        self.req_id = 0

    async def get_or_create_tab(self, target_type: str, room_identifier: str = ""):
        try:
            targets = requests.get(f"{self.cdp_url}/json", timeout=5).json()
        except Exception as e:
            print(f"[!] Error: Cannot connect to Brave on port 9222. Ensure Brave is running ({e})")
            sys.exit(1)

        # Match existing tab
        for t in targets:
            if t.get("type") != "page":
                continue
            url = t.get("url", "")
            title = t.get("title", "")

            if target_type == "copilot" and ("m365.cloud.microsoft" in url or (room_identifier and room_identifier in url)):
                return t
            elif target_type == "okmd" and "okmd.or.th" in url:
                return t
            elif target_type == "aipass" and "aipass.net" in url:
                return t
            elif room_identifier and (room_identifier in url or room_identifier in title):
                return t

        # If not open, open new tab
        print(f"[INFO] Tab for {target_type} not open. Creating new tab via CDP...")
        nav_url = "https://playground.okmd.or.th/chat"
        if target_type == "aipass":
            nav_url = "https://de.aipass.net/chat"
        elif target_type == "copilot":
            nav_url = room_identifier if room_identifier.startswith("http") else f"https://m365.cloud.microsoft/chat/conversation/{room_identifier}"

        new_tab = requests.put(f"{self.cdp_url}/json/new?{nav_url}", timeout=5).json()
        await asyncio.sleep(4)
        return new_tab

    async def connect_ws(self, ws_url: str):
        self.ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024)

    async def send_cmd(self, method: str, params: dict = None):
        self.req_id += 1
        curr_id = self.req_id
        req = json.dumps({"id": curr_id, "method": method, "params": params or {}})
        await self.ws.send(req)
        while True:
            resp = await self.ws.recv()
            data = json.loads(resp)
            if data.get("id") == curr_id:
                return data.get("result", {})

    async def eval_js(self, expression: str):
        res = await self.send_cmd("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True
        })
        val = res.get("result", {}).get("value")
        return val

    async def close(self):
        if self.ws:
            await self.ws.close()


async def execute_bridge(target: str, message: str, out_file: str, model: str = "", room_id: str = "", timeout_sec: int = 240):
    client = BraveCdpClient()
    tab = await client.get_or_create_tab(target, room_id)
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        print(f"[!] No webSocketDebuggerUrl found for tab: {tab}")
        sys.exit(1)

    print(f"[OK] Connecting via WebSocket CDP to [{target.upper()}]: {tab.get('title')}", flush=True)
    await client.connect_ws(ws_url)

    # Bring tab to front
    await client.send_cmd("Page.bringToFront")
    await asyncio.sleep(0.5)

    escaped_msg = json.dumps(message)
    escaped_model = json.dumps(model)

    if target == "okmd":
        print(f"[1] OKMD: Configuring model '{model or 'default'}' & injecting prompt...", flush=True)
        inject_script = f"""
        (() => {{
            const targetModel = {escaped_model}.trim().toLowerCase();

            // 1. If a specific model is requested, open dropdown and select it
            if (targetModel) {{
                // Find model dropdown trigger
                const dropdownTriggers = Array.from(document.querySelectorAll('div.dropdown, div.icon.text-muted, [class*="dropdown-toggle"], button'));
                const trigger = dropdownTriggers.find(el => {{
                    const t = (el.innerText || '').toLowerCase();
                    return t.includes('auto router') || t.includes('auto select') || t.includes('model') || t.includes('openai') || t.includes('deepseek');
                }});
                if (trigger) {{
                    trigger.click();
                }}

                // Wait for dropdown items and click the match
                setTimeout(() => {{
                    const modelItems = Array.from(document.querySelectorAll('a.dropdown-item-models, a.dropdown-item, li, button'));
                    const selected = modelItems.find(a => {{
                        const text = (a.innerText || '').toLowerCase();
                        return text.includes(targetModel);
                    }});
                    if (selected) {{
                        selected.click();
                    }}
                }}, 300);
            }}

            // 2. Switch to Reasoning / Deep Research if requested or available
            const buttons = Array.from(document.querySelectorAll('button, div[role="button"]'));
            const reasoningBtn = buttons.find(b => {{
                const t = b.innerText || '';
                return t.includes('Reasoning (Pro)') || t.includes('Reasoning') || t.includes('Deep Research');
            }});
            if (reasoningBtn) {{
                reasoningBtn.click();
            }}

            // 3. Select input box
            const ta = document.querySelector('textarea.input-message') || document.querySelector('textarea:not([type="search"])') || document.querySelector('textarea');
            if (!ta) return {{ success: false, error: 'Cannot find textarea.input-message' }};

            ta.focus();
            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
            if (nativeSetter) {{
                nativeSetter.call(ta, {escaped_msg});
            }} else {{
                ta.value = {escaped_msg};
            }}
            ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
            ta.dispatchEvent(new Event('change', {{ bubbles: true }}));

            // 4. Click Send Button
            setTimeout(() => {{
                const sendBtn = document.querySelector('button.btn-sent-message') || 
                                Array.from(document.querySelectorAll('button')).find(b => b.querySelector('svg') && !b.innerText && b.type !== 'button') ||
                                document.querySelector('button[type="submit"]');
                if (sendBtn) {{
                    sendBtn.click();
                }} else {{
                    ta.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                }}
            }}, 600);

            return {{ success: true }};
        }})()
        """
        res = await client.eval_js(inject_script)
        print(f"[2] Injection result: {res}", flush=True)

    elif target == "aipass":
        print(f"[1] AIPass: Selecting model '{model or 'Claude Opus 5'}' & injecting prompt...", flush=True)
        inject_script = f"""
        (() => {{
            const targetModel = ({escaped_model} || 'Claude Opus 5').trim().toLowerCase();

            // 1. Ensure requested model is selected
            const cards = Array.from(document.querySelectorAll('div, li, article, button'));
            const modelCard = cards.find(c => (c.innerText || '').toLowerCase().includes(targetModel));
            if (modelCard) {{
                const btn = modelCard.tagName === 'BUTTON' ? modelCard : modelCard.querySelector('button');
                if (btn) btn.click();
            }}

            // 2. Select textarea
            const ta = document.querySelector('textarea');
            if (!ta) return {{ success: false, error: 'Cannot find textarea' }};

            ta.focus();
            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
            if (nativeSetter) {{
                nativeSetter.call(ta, {escaped_msg});
            }} else {{
                ta.value = {escaped_msg};
            }}
            ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
            ta.dispatchEvent(new Event('change', {{ bubbles: true }}));

            // 3. Click Send
            setTimeout(() => {{
                const allBtns = Array.from(document.querySelectorAll('button'));
                let sendBtn = allBtns.find(b => {{
                    const label = b.getAttribute('aria-label') || '';
                    return label.includes('Send') || label.includes('ส่ง');
                }});
                if (!sendBtn) {{
                    sendBtn = allBtns.filter(b => b.offsetParent !== null && b.querySelector('svg')).pop();
                }}
                if (sendBtn) {{
                    sendBtn.click();
                }} else {{
                    ta.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                }}
            }}, 500);

            return {{ success: true }};
        }})()
        """
        res = await client.eval_js(inject_script)
        print(f"[2] Injection result: {res}", flush=True)

    elif target == "copilot":
        print("[1] Copilot: Injecting prompt into chat input...", flush=True)
        inject_script = f"""
        (() => {{
            const inputEl = document.querySelector("span[aria-label='Message Copilot'], div[contenteditable='true'], [role='textbox'], textarea");
            if (!inputEl) return {{ success: false, error: 'Cannot find Copilot input box' }};

            inputEl.focus();
            if (inputEl.tagName === 'TEXTAREA' || inputEl.tagName === 'INPUT') {{
                inputEl.value = {escaped_msg};
                inputEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }} else {{
                inputEl.innerText = {escaped_msg};
                inputEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}

            setTimeout(() => {{
                const submitBtn = document.querySelector("button[aria-label*='Submit'], button[aria-label*='Send'], button[type='submit']");
                if (submitBtn) submitBtn.click();
                else inputEl.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
            }}, 400);

            return {{ success: true }};
        }})()
        """
        res = await client.eval_js(inject_script)
        print(f"[2] Injection result: {res}", flush=True)

    print(f"[3] Prompt sent to [{target.upper()}]. Monitoring response...", flush=True)

    prev_len = 0
    stable_count = 0
    start = time.time()
    snippet = message[:35].strip()

    while time.time() - start < timeout_sec:
        await asyncio.sleep(4)
        text = await client.eval_js("document.body.innerText") or ""

        if snippet:
            idx = text.rfind(snippet)
            if idx != -1:
                text = text[idx:]

        cur_len = len(text)
        print(f"  Streaming {target} response: {cur_len} chars...", flush=True)

        # Finished when content has grown and remains unchanged for multiple consecutive checks
        if cur_len > 300 and cur_len == prev_len:
            stable_count += 1
            if stable_count >= 3:
                print(f"\n[OK] {target.upper()} response finished & stabilized ({cur_len} chars)!", flush=True)
                with open(out_file, "w", encoding="utf-8") as f:
                    f.write(text)
                print(f"[OK] Successfully saved response to {out_file}")
                break
        else:
            stable_count = 0
            prev_len = cur_len

    await client.close()


def main():
    parser = argparse.ArgumentParser(description="Universal Brave Web AI Bridge CLI (WebSocket CDP)")
    parser.add_argument("action", choices=["ask", "send", "read"])
    parser.add_argument("--target", choices=["copilot", "okmd", "aipass"], default="copilot", help="Target Web AI platform")
    parser.add_argument("--model", default="", help="Specific AI Model to select (e.g. deepseek, claude, gemini, openai)")
    parser.add_argument("--room", default="", help="Room URL or conversation ID (for Copilot)")
    parser.add_argument("--msg-file", required=True, help="Path to prompt file")
    parser.add_argument("--out-file", default="ai_response.md", help="Path to save reply")
    parser.add_argument("--timeout", type=int, default=240, help="Max timeout in seconds")

    args = parser.parse_args()

    with open(args.msg_file, "r", encoding="utf-8") as f:
        msg = f.read()

    asyncio.run(execute_bridge(args.target, msg, args.out_file, model=args.model, room_id=args.room, timeout_sec=args.timeout))


if __name__ == "__main__":
    main()
