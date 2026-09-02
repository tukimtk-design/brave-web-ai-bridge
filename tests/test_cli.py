from unittest.mock import AsyncMock, mock_open, patch

import pytest

from brave_web_ai_bridge import main


@patch('sys.argv', ['brave_web_ai_bridge.py', 'ask', '--target', 'okmd', '--model', 'deepseek', '--msg-file', 'prompt.txt', '--out-file', 'okmd_reply.md'])
@patch('builtins.open', new_callable=mock_open, read_data="Hello AI")
@patch('brave_web_ai_bridge.execute_bridge', new_callable=AsyncMock)
def test_cli_args_parsing_details(mock_execute_bridge, mock_file):
    main()
    mock_execute_bridge.assert_called_once_with('okmd', 'Hello AI', 'okmd_reply.md', model='deepseek', room_id='', timeout_sec=240)

@pytest.mark.asyncio
@patch('brave_web_ai_bridge.requests.get')
async def test_cli_error_handling_brave_not_running(mock_get, capsys):
    import requests

    from brave_web_ai_bridge import BraveCdpClient
    
    # Simulate connection error
    mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
    
    client = BraveCdpClient()
    
    with pytest.raises(SystemExit) as exit_info:
        await client.get_or_create_tab("copilot", "")
        
    assert exit_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "[!] Error: Cannot connect to Brave on port 9222" in captured.out
    assert "Ensure Brave is running" in captured.out
