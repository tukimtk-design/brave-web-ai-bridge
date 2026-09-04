import json
import os
import tempfile
import time

import requests

from brave_web_ai_bridge import TARGETS, execute_bridge


def handle_ping() -> dict:
    """Returns CDP 9222 status without making AI queries."""
    try:
        resp = requests.get("http://127.0.0.1:9222/json", timeout=2)
        resp.raise_for_status()
        return {"status": "OK", "message": f"CDP 9222 status: OK (Found {len(resp.json())} targets)"}
    except Exception as e:
        return {"status": "Error", "message": f"CDP 9222 status: Error ({e})"}

def handle_list_targets() -> dict:
    """Lists active Web AI tabs matching allowed targets."""
    return {"targets": list(TARGETS.keys())}

async def handle_ask(params: dict) -> dict:
    """Sends a prompt to the specified target and returns the response."""
    target = params.get("target")
    prompt = params.get("prompt")
    
    if not target or not prompt:
        return {"error": "INVALID_PARAMS", "message": "Parameters 'target' and 'prompt' are required."}
        
    if target not in TARGETS:
        return {"error": "INVALID_TARGET", "message": f"Target '{target}' not supported. Supported: {list(TARGETS.keys())}"}

    room_id = params.get("room_id", "")
    max_output_chars = params.get("max_output_chars", 0)
    timeout_seconds = params.get("timeout_seconds", 240)
    new_session = params.get("new_session", False)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as pf:
        pf.write(prompt)
        prompt_file = pf.name

    out_file = prompt_file.replace(".txt", "_out.txt")

    start_time = time.time()
    try:
        success = await execute_bridge(
            target=target,
            message=prompt,
            out_file=out_file,
            room_id=room_id,
            timeout_sec=timeout_seconds,
            new_session=new_session
        )
        latency_seconds = time.time() - start_time
        
        if not success:
            return {"error": "EXECUTION_FAILED", "message": "Error: execution failed or timed out."}

        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                content = f.read()
                
            truncated = False
            if max_output_chars > 0 and len(content) > max_output_chars:
                content = content[:max_output_chars]
                truncated = True
                
            return {
                "response": content,
                "telemetry": {
                    "char_count": len(content),
                    "latency_seconds": round(latency_seconds, 2),
                    "truncated": truncated
                }
            }
        else:
            return {"error": "NO_RESPONSE", "message": "Error: response file not found."}
    finally:
        if os.path.exists(prompt_file):
            os.remove(prompt_file)
        if os.path.exists(out_file):
            os.remove(out_file)

async def dispatch_action(action: str, params: dict) -> str:
    """Dispatches the action to the correct handler."""
    if action == "list_actions":
        return json.dumps({
            "actions": {
                "list_actions": "Discover all available bridge operations and parameter specifications",
                "ping": "Check Brave CDP 9222 connection health without querying AI models",
                "list_targets": "List supported Web AI target identifiers ('copilot', 'okmd', 'aipass')",
                "ask": "Send prompt to target Web AI and receive response with telemetry metrics"
            }
        })
    elif action == "ping":
        result = handle_ping()
        return json.dumps(result)
    elif action == "list_targets":
        result = handle_list_targets()
        return json.dumps(result)
    elif action == "ask":
        result = await handle_ask(params)
        return json.dumps(result)
    else:
        return json.dumps({"error": "INVALID_ACTION", "message": f"Unknown action '{action}'."})
