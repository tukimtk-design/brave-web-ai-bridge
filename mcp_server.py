import logging
import sys

from mcp.server.fastmcp import FastMCP

from actions import dispatch_action, handle_ask, handle_list_targets, handle_ping

# Ensure all logging goes to stderr so stdout is strictly for JSON-RPC
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[%(levelname)s] %(message)s")

mcp_server = FastMCP("brave_web_ai_bridge")

@mcp_server.tool(name="bridge_ops", description="Adaptive Single-Gateway for Brave Web AI Bridge operations. Use action 'list_actions' to discover available commands, or specify action and params to execute.")
async def bridge_ops(action: str, params: dict | None = None) -> str:
    """Adaptive Single-Gateway for Brave Web AI Bridge operations. Use action 'list_actions' to discover available commands, or specify action and params to execute."""
    if params is None:
        params = {}
    return await dispatch_action(action, params)

@mcp_server.tool(description="[DEPRECATED: Use bridge_ops with action='ping'] Returns CDP 9222 status without making AI queries.")
def bridge_ping() -> str:
    """Returns CDP 9222 status without making AI queries. Kept for backwards compatibility."""
    result = handle_ping()
    return result["message"]

@mcp_server.tool(description="[DEPRECATED: Use bridge_ops with action='list_targets'] Lists active Web AI tabs matching allowed targets.")
def bridge_list_targets() -> list[str]:
    """Lists active Web AI tabs matching allowed targets. Kept for backwards compatibility."""
    result = handle_list_targets()
    return result["targets"]

@mcp_server.tool(description="[DEPRECATED: Use bridge_ops with action='ask'] Sends a prompt to the specified target and returns the response.")
async def bridge_ask(
    target: str,
    prompt: str,
    room_id: str = "",
    max_output_chars: int = 0,
    timeout_seconds: int = 240,
    new_session: bool = False
) -> str:
    """Sends a prompt to the specified target and returns the response. Kept for backwards compatibility."""
    params = {
        "target": target,
        "prompt": prompt,
        "room_id": room_id,
        "max_output_chars": max_output_chars,
        "timeout_seconds": timeout_seconds,
        "new_session": new_session
    }
    result = await handle_ask(params)
    if "error" in result:
        return result["message"]
    return result["response"]

def main():
    mcp_server.run()

if __name__ == "__main__":
    main()
