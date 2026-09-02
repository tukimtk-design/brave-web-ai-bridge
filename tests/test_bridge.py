from unittest.mock import patch

import pytest

from brave_web_ai_bridge import BraveCdpClient


@pytest.fixture
def cdp_client():
    return BraveCdpClient()

@pytest.mark.asyncio
@patch('brave_web_ai_bridge.requests.get')
@patch('brave_web_ai_bridge.requests.put')
async def test_get_or_create_tab_copilot_existing(mock_put, mock_get, cdp_client):
    # Mock /json response
    mock_get.return_value.json.return_value = [
        {"id": "1", "type": "page", "url": "https://m365.cloud.microsoft/chat/conversation/123", "title": "Copilot"}
    ]
    
    # Test with exact room
    tab = await cdp_client.get_or_create_tab("copilot", "123")
    assert tab["id"] == "1"
    assert not mock_put.called
    
    # Test with general copilot URL
    tab = await cdp_client.get_or_create_tab("copilot", "")
    assert tab["id"] == "1"
    assert not mock_put.called

@pytest.mark.asyncio
@patch('brave_web_ai_bridge.requests.get')
@patch('brave_web_ai_bridge.requests.put')
async def test_get_or_create_tab_copilot_create_new(mock_put, mock_get, cdp_client):
    mock_get.return_value.json.return_value = []
    mock_put.return_value.json.return_value = {"id": "2", "type": "page", "url": "https://m365.cloud.microsoft/chat/conversation/456"}
    
    tab = await cdp_client.get_or_create_tab("copilot", "456")
    assert tab["id"] == "2"
    mock_put.assert_called_once()
    assert "https://m365.cloud.microsoft/chat/conversation/456" in mock_put.call_args[0][0]

@pytest.mark.asyncio
@patch('brave_web_ai_bridge.requests.get')
@patch('brave_web_ai_bridge.requests.put')
async def test_get_or_create_tab_okmd(mock_put, mock_get, cdp_client):
    mock_get.return_value.json.return_value = [
        {"id": "3", "type": "page", "url": "https://playground.okmd.or.th/chat", "title": "OKMD"}
    ]
    
    tab = await cdp_client.get_or_create_tab("okmd", "")
    assert tab["id"] == "3"
    assert not mock_put.called
    
@pytest.mark.asyncio
@patch('brave_web_ai_bridge.requests.get')
@patch('brave_web_ai_bridge.requests.put')
async def test_get_or_create_tab_aipass(mock_put, mock_get, cdp_client):
    mock_get.return_value.json.return_value = [
        {"id": "4", "type": "page", "url": "https://de.aipass.net/chat", "title": "AIPass"}
    ]
    
    tab = await cdp_client.get_or_create_tab("aipass", "")
    assert tab["id"] == "4"
    assert not mock_put.called

@pytest.mark.asyncio
@patch('brave_web_ai_bridge.BraveCdpClient.eval_js')
@patch('brave_web_ai_bridge.BraveCdpClient.get_or_create_tab')
@patch('brave_web_ai_bridge.BraveCdpClient.connect_ws')
@patch('brave_web_ai_bridge.BraveCdpClient.send_cmd')
@patch('brave_web_ai_bridge.BraveCdpClient.press_enter')
@patch('brave_web_ai_bridge.BraveCdpClient.close')
async def test_text_injection_copilot(mock_close, mock_press_enter, mock_send_cmd, mock_connect, mock_get_tab, mock_eval_js, tmp_path):
    # Mock tab info
    mock_get_tab.return_value = {"id": "1", "type": "page", "url": "https://m365.cloud.microsoft/chat", "title": "Copilot", "webSocketDebuggerUrl": "ws://dummy"}
    
    # Mock text retrieval to simulate response stream stabilization
    mock_eval_js.side_effect = [{"success": True}, "response text", "response text", "response text"]

    out_file = tmp_path / "out.md"
    
    from brave_web_ai_bridge import execute_bridge
    await execute_bridge("copilot", "Hello Copilot", str(out_file), room_id="123", timeout_sec=2)
    
    # Check that eval_js was called with injection script containing document.execCommand('insertText')
    eval_calls = mock_eval_js.call_args_list
    assert len(eval_calls) > 0
    inject_script_call = eval_calls[0]
    inject_script = inject_script_call[0][0]
    assert "document.execCommand('insertText'" in inject_script
    
    # Check for Thai button labels
    assert "aria-label*='ส่งข้อความ'" in inject_script
    assert "aria.includes('ส่ง')" in inject_script

@pytest.mark.asyncio
@patch('brave_web_ai_bridge.BraveCdpClient.send_cmd')
async def test_cdp_hardware_enter_key(mock_send_cmd, cdp_client):
    await cdp_client.press_enter()
    
    assert mock_send_cmd.call_count == 2
    
    call_args_down = mock_send_cmd.call_args_list[0][0]
    call_args_up = mock_send_cmd.call_args_list[1][0]
    
    assert call_args_down[0] == "Input.dispatchKeyEvent"
    assert call_args_down[1]["type"] == "rawKeyDown"
    assert call_args_down[1].get("windowsVirtualKeyCode", call_args_down[1].get("virtualKeyCode")) == 13
    
    assert call_args_up[0] == "Input.dispatchKeyEvent"
    assert call_args_up[1]["type"] == "keyUp"
    assert call_args_up[1].get("windowsVirtualKeyCode", call_args_up[1].get("virtualKeyCode")) == 13

@pytest.mark.asyncio
@patch('brave_web_ai_bridge.BraveCdpClient.eval_js')
@patch('brave_web_ai_bridge.BraveCdpClient.get_or_create_tab')
@patch('brave_web_ai_bridge.BraveCdpClient.connect_ws')
@patch('brave_web_ai_bridge.BraveCdpClient.send_cmd')
@patch('brave_web_ai_bridge.BraveCdpClient.press_enter')
@patch('brave_web_ai_bridge.BraveCdpClient.close')
async def test_response_streaming_stabilization(mock_close, mock_press_enter, mock_send_cmd, mock_connect, mock_get_tab, mock_eval_js, tmp_path):
    mock_get_tab.return_value = {"id": "1", "type": "page", "url": "https://de.aipass.net/chat", "title": "AIPass", "webSocketDebuggerUrl": "ws://dummy"}
    
    # eval_js is called:
    # 1. To inject script
    # Then in a loop:
    # 2. scroll script
    # 3. get text
    # 4. scroll script
    # 5. get text...
    
    responses = [
        {"success": True}, # initial injection
        None, # scroll
        "a" * 100, # text length 100, cur_len 100, prev_len 0. cur_len > 300 is false. stable_count 0. prev_len 100.
        None, # scroll
        "a" * 350, # text length 350, cur_len 350, prev_len 100. cur_len > 300 is true, cur_len == prev_len is false. stable_count 0. prev_len 350.
        None, # scroll
        "a" * 350, # text length 350, cur_len 350, prev_len 350. stable_count 1.
        None, # scroll
        "a" * 350, # text length 350, cur_len 350, prev_len 350. stable_count 2.
        None, # scroll
        "a" * 350, # text length 350, cur_len 350, prev_len 350. stable_count 3. break!
    ]
    
    mock_eval_js.side_effect = responses
    
    out_file = tmp_path / "out_stabilized.md"
    
    from brave_web_ai_bridge import execute_bridge
    await execute_bridge("aipass", "Hello AIPass", str(out_file), model="Claude", room_id="", timeout_sec=20)
    
    assert mock_close.called
    assert out_file.exists()
    with open(out_file, "r") as f:
        content = f.read()
        assert len(content) == 350

@pytest.mark.asyncio
@patch('brave_web_ai_bridge.BraveCdpClient.eval_js')
@patch('brave_web_ai_bridge.BraveCdpClient.get_or_create_tab')
@patch('brave_web_ai_bridge.BraveCdpClient.connect_ws')
@patch('brave_web_ai_bridge.BraveCdpClient.send_cmd')
@patch('brave_web_ai_bridge.BraveCdpClient.press_enter')
@patch('brave_web_ai_bridge.BraveCdpClient.close')
async def test_response_streaming_timeout(mock_close, mock_press_enter, mock_send_cmd, mock_connect, mock_get_tab, mock_eval_js, tmp_path):
    mock_get_tab.return_value = {"id": "1", "type": "page", "url": "https://de.aipass.net/chat", "title": "AIPass", "webSocketDebuggerUrl": "ws://dummy"}
    
    # Simulate not stabilizing within timeout
    # timeout_sec=1 -> wait 4 sec each loop, so loop runs 0 times or maybe 1 time and breaks if time > timeout_sec
    # We set timeout_sec=0 so it exits immediately after the start
    
    mock_eval_js.side_effect = [{"success": True}] # initial injection
    
    out_file = tmp_path / "out_timeout.md"
    
    from brave_web_ai_bridge import execute_bridge
    await execute_bridge("aipass", "Hello AIPass", str(out_file), model="Claude", room_id="", timeout_sec=0)
    
    assert mock_close.called
    assert not out_file.exists() # Should not have reached file writing
