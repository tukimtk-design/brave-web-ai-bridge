import logging
import os
import sys
import tempfile

import requests
from mcp.server.fastmcp import FastMCP

from brave_web_ai_bridge import TARGETS, execute_bridge

# Ensure all logging goes to stderr so stdout is strictly for JSON-RPC
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[%(levelname)s] %(message)s")

mcp_server = FastMCP("brave_web_ai_bridge")

@mcp_server.tool()
def bridge_ping() -> str:
    """Returns CDP 9222 status without making AI queries."""
    try:
        resp = requests.get("http://127.0.0.1:9222/json", timeout=2)
        resp.raise_for_status()
        return f"CDP 9222 status: OK (Found {len(resp.json())} targets)"
    except Exception as e:
        return f"CDP 9222 status: Error ({e})"

@mcp_server.tool()
def bridge_list_targets() -> list[str]:
    """Lists active Web AI tabs matching allowed targets."""
    return list(TARGETS.keys())

@mcp_server.tool()
async def bridge_ask(
    target: str,
    prompt: str,
    room_id: str = "",
    max_output_chars: int = 0,
    timeout_seconds: int = 240,
    new_session: bool = False
) -> str:
    """Sends a prompt to the specified target and returns the response."""
    if target not in TARGETS:
        return f"Error: Target '{target}' not supported. Supported: {list(TARGETS.keys())}"

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as pf:
        pf.write(prompt)
        prompt_file = pf.name

    out_file = prompt_file.replace(".txt", "_out.txt")

    try:
        success = await execute_bridge(
            target=target,
            message=prompt,
            out_file=out_file,
            room_id=room_id,
            timeout_sec=timeout_seconds,
            new_session=new_session
        )
        if not success:
            return "Error: execution failed or timed out."

        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                content = f.read()
            if max_output_chars > 0 and len(content) > max_output_chars:
                content = content[:max_output_chars]
            return content
        else:
            return "Error: response file not found."
    finally:
        if os.path.exists(prompt_file):
            os.remove(prompt_file)
        if os.path.exists(out_file):
            os.remove(out_file)

def main():
    mcp_server.run()

if __name__ == "__main__":
    main()
