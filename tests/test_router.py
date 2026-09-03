import asyncio
from unittest.mock import AsyncMock, mock_open, patch

import pytest

from router import aipass_router
from router.aipass_router import (
    TASK_ROUTING,
    apply_failure_cooldown,
    get_candidates_for_task,
    record_model_success,
    set_model_cooldown,
)


@pytest.fixture
def state_file(tmp_path):
    return str(tmp_path / "model_status.json")


def test_task_routing_has_three_candidates_per_class():
    for task_class, candidates in TASK_ROUTING.items():
        assert len(candidates) == 3, f"{task_class} must have 3 candidates"


def test_candidates_follow_static_order_without_state(state_file):
    assert get_candidates_for_task("deep-reasoning", state_file) == ["Claude Opus 5", "DeepSeek R1", "Gemini 2.5 Pro"]
    assert get_candidates_for_task("fast", state_file) == ["Gemini 2.5 Flash", "DeepSeek V3", "Claude Sonnet 5"]


def test_cooldown_pushes_model_to_end_of_candidate_list(state_file):
    set_model_cooldown("Claude Opus 5", 15, state_file)
    candidates = get_candidates_for_task("deep-reasoning", state_file)
    assert candidates == ["DeepSeek R1", "Gemini 2.5 Pro", "Claude Opus 5"]


def test_cooldown_expires(state_file):
    set_model_cooldown("Claude Opus 5", 15, state_file)
    # Force the cooldown into the past
    state = aipass_router.load_state(state_file)
    state["models"]["Claude Opus 5"]["cooldownUntil"] = 0
    aipass_router.save_state(state, state_file)
    assert get_candidates_for_task("deep-reasoning", state_file)[0] == "Claude Opus 5"


def test_cooldown_update_preserves_existing_stats(state_file):
    """Regression per merge spec: never overwrite the whole entry —
    successCount/lastLatencySeconds must survive a later cooldown."""
    record_model_success("Claude Opus 5", 12.5, state_file)
    set_model_cooldown("Claude Opus 5", 15, state_file)
    entry = aipass_router.load_state(state_file)["models"]["Claude Opus 5"]
    assert entry["successCount"] == 1
    assert entry["lastLatencySeconds"] == 12.5
    assert entry["failCount"] == 1
    assert entry["status"] == "COOLDOWN"


def test_record_model_success_clears_cooldown_and_bumps_success(state_file):
    set_model_cooldown("DeepSeek R1", 15, state_file)
    record_model_success("DeepSeek R1", 3.2, state_file)
    entry = aipass_router.load_state(state_file)["models"]["DeepSeek R1"]
    assert entry["status"] == "AVAILABLE"
    assert entry["cooldownUntil"] == 0
    assert entry["successCount"] == 1
    assert entry["lastLatencySeconds"] == 3.2
    assert entry["failCount"] == 1  # preserved from the earlier cooldown


def test_failure_cooldown_mapping(state_file):
    apply_failure_cooldown("MODEL_ERROR: quota exceeded", "A", state_file)
    apply_failure_cooldown("SEND_FAILED: no verification", "B", state_file)
    apply_failure_cooldown("MODEL_SWITCH_FAILED: item_not_found", "C", state_file)
    state = aipass_router.load_state(state_file)
    now = aipass_router.load_state(state_file)["lastUpdated"]
    assert state["models"]["A"]["cooldownUntil"] - now > 14 * 60   # 15 min
    assert state["models"]["B"]["cooldownUntil"] - now > 14 * 60   # 15 min
    assert 4 * 60 < state["models"]["C"]["cooldownUntil"] - now <= 5 * 60  # 5 min


def test_unknown_task_class_falls_back_to_default_candidates(state_file):
    assert get_candidates_for_task("unknown-class", state_file) == ["Claude Sonnet 5", "Claude Opus 5", "DeepSeek R1"]


@patch('sys.argv', ['brave_web_ai_bridge.py', 'ask', '--target', 'aipass', '--task', 'deep-reasoning', '--msg-file', 'prompt.txt', '--out-file', 'out.md'])
@patch('builtins.open', new_callable=mock_open, read_data="Hello AI")
@patch('brave_web_ai_bridge.execute_bridge', new_callable=AsyncMock)
def test_cli_task_arg_passed_through(mock_execute_bridge, mock_file):
    """--task must reach execute_bridge as task_class while --model stays empty
    (router mode is triggered by task without model)."""
    from brave_web_ai_bridge import main
    main()
    mock_execute_bridge.assert_called_once_with('aipass', 'Hello AI', 'out.md', model='', room_id='', timeout_sec=240, task_class='deep-reasoning')


@pytest.mark.asyncio
@patch('brave_web_ai_bridge.record_model_success')
@patch('brave_web_ai_bridge.get_candidates_for_task')
async def test_execute_aipass_routed_success_writes_file(mock_candidates, mock_success, tmp_path):
    import brave_web_ai_bridge as bridge

    mock_candidates.return_value = ["ModelA", "ModelB"]
    out_file = tmp_path / "out.md"

    with patch.object(bridge.AipassAdapter, 'attempt_with_model', new_callable=AsyncMock) as mock_attempt:
        mock_attempt.return_value = "the answer"
        ok = await bridge.execute_aipass_routed(
            bridge.BraveCdpClient(), "code", "prompt", str(out_file), timeout_sec=30)

    assert ok is True
    assert out_file.read_text(encoding="utf-8") == "the answer"
    # First candidate succeeded: success recorded, no cooldown applied
    mock_success.assert_called_once()
    called_model = mock_success.call_args[0][0]
    assert called_model == "ModelA"


@pytest.mark.asyncio
@patch('brave_web_ai_bridge.apply_failure_cooldown')
@patch('brave_web_ai_bridge.record_model_success')
@patch('brave_web_ai_bridge.get_candidates_for_task')
async def test_execute_aipass_routed_failover_then_exhaustion(mock_candidates, mock_success, mock_cooldown, tmp_path):
    """First model fails -> cooldown applied -> second succeeds. If all fail,
    the loop returns False (CLI maps to exit code 2)."""
    import brave_web_ai_bridge as bridge

    mock_candidates.return_value = ["ModelA", "ModelB"]
    out_file = tmp_path / "out.md"

    with patch.object(bridge.AipassAdapter, 'attempt_with_model', new_callable=AsyncMock) as mock_attempt:
        mock_attempt.side_effect = [
            bridge.BridgeError("MODEL_ERROR: quota exceeded"),
            "recovered answer",
        ]
        ok = await bridge.execute_aipass_routed(
            bridge.BraveCdpClient(), "code", "prompt", str(out_file), timeout_sec=30)

    assert ok is True
    assert out_file.read_text(encoding="utf-8") == "recovered answer"
    mock_cooldown.assert_called_once()
    assert "MODEL_ERROR" in mock_cooldown.call_args[0][0]

    # Exhaustion: every candidate fails
    with patch.object(bridge.AipassAdapter, 'attempt_with_model', new_callable=AsyncMock) as mock_attempt2:
        mock_attempt2.side_effect = bridge.BridgeError("SEND_FAILED: not verified")
        ok = await bridge.execute_aipass_routed(
            bridge.BraveCdpClient(), "code", "prompt", str(tmp_path / "out2.md"), timeout_sec=30)

    assert ok is False
