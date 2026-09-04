from unittest.mock import MagicMock, patch

import pytest

# Import the server tools
from mcp_server import bridge_ask, bridge_list_targets, bridge_ping


@pytest.mark.asyncio
@patch("mcp_server.requests.get")
async def test_bridge_ping_success(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"id": "1", "type": "page"}]
    mock_get.return_value = mock_resp

    result = bridge_ping()
    assert "OK" in result
    assert "Found 1" in result

@pytest.mark.asyncio
@patch("mcp_server.requests.get")
async def test_bridge_ping_error(mock_get):
    mock_get.side_effect = Exception("Connection refused")

    result = bridge_ping()
    assert "Error" in result
    assert "Connection refused" in result

@pytest.mark.asyncio
async def test_bridge_list_targets():
    result = bridge_list_targets()
    assert "copilot" in result
    assert "okmd" in result
    assert "aipass" in result

@pytest.mark.asyncio
@patch("brave_web_ai_bridge.BraveCdpClient.eval_js")
@patch("brave_web_ai_bridge.BraveCdpClient.get_or_create_tab")
@patch("brave_web_ai_bridge.BraveCdpClient.connect_ws")
@patch("brave_web_ai_bridge.BraveCdpClient.send_cmd")
@patch("brave_web_ai_bridge.BraveCdpClient.press_enter")
@patch("brave_web_ai_bridge.BraveCdpClient.close")
async def test_bridge_ask_success(mock_close, mock_press_enter, mock_send_cmd, mock_connect, mock_get_tab, mock_eval_js):
    # Mocking get_or_create_tab
    mock_get_tab.return_value = {
        "id": "1",
        "type": "page",
        "url": "https://m365.cloud.microsoft/chat",
        "title": "Copilot",
        "webSocketDebuggerUrl": "ws://dummy"
    }

    # Custom side effect function to match what `execute_bridge` does
    # First call is injection
    # If copilot, there's a click button call
    # Then loop: scroll call -> read call

    calls = []
    def eval_js_side_effect(script, *args, **kwargs):
        calls.append(script)
        if "nativeSetter" in script or "document.execCommand('insertText'" in script:
            return {"success": True} # Injection
        if "scrollBtn" in script:
            return None # Scroll
        if "fai-CopilotMessage__content" in script:
            return "A" * 350 # Content read
        return None

    mock_eval_js.side_effect = eval_js_side_effect

    result = await bridge_ask(
        target="copilot",
        prompt="Test prompt",
        room_id="123",
        timeout_seconds=20,
    )

    assert "A" * 350 in result
    mock_close.assert_called_once()
    mock_connect.assert_called_once_with("ws://dummy")

@pytest.mark.asyncio
@patch("brave_web_ai_bridge.BraveCdpClient.eval_js")
@patch("brave_web_ai_bridge.BraveCdpClient.get_or_create_tab")
@patch("brave_web_ai_bridge.BraveCdpClient.connect_ws")
@patch("brave_web_ai_bridge.BraveCdpClient.send_cmd")
@patch("brave_web_ai_bridge.BraveCdpClient.press_enter")
@patch("brave_web_ai_bridge.BraveCdpClient.close")
async def test_bridge_ask_max_chars(mock_close, mock_press_enter, mock_send_cmd, mock_connect, mock_get_tab, mock_eval_js):
    mock_get_tab.return_value = {
        "id": "1",
        "type": "page",
        "url": "https://m365.cloud.microsoft/chat",
        "title": "Copilot",
        "webSocketDebuggerUrl": "ws://dummy"
    }

    calls = []
    def eval_js_side_effect(script, *args, **kwargs):
        calls.append(script)
        if "nativeSetter" in script or "document.execCommand('insertText'" in script:
            return {"success": True} # Injection
        if "scrollBtn" in script:
            return None # Scroll
        if "fai-CopilotMessage__content" in script:
            return "B" * 350 # Content read
        return None

    mock_eval_js.side_effect = eval_js_side_effect

    result = await bridge_ask(
        target="copilot",
        prompt="Test prompt",
        room_id="123",
        max_output_chars=10,
        timeout_seconds=20,
    )

    assert len(result) == 10
    assert result == "B" * 10

@pytest.mark.asyncio
async def test_bridge_ask_invalid_target():
    result = await bridge_ask(target="invalid", prompt="test")
    assert "Error: Target 'invalid' not supported" in result
