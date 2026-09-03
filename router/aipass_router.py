"""AIPass model router and cooldown manager.

Ported from aipass-auto-router/scripts/check_models.py (Phase 2 Reliability
Hardening, commits 6b27657/6b5e420) into the brave-web-ai-bridge repo.

State lives in state/model_status.json at the repo root. Per-model entries are
updated incrementally (never overwritten wholesale) so stats such as
successCount / failCount / lastLatencySeconds survive across runs.
"""
import json
import os
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(REPO_ROOT, "state", "model_status.json")

TASK_ROUTING = {
    "deep-reasoning": ["Claude Opus 5", "DeepSeek R1", "Gemini 2.5 Pro"],
    "code": ["Claude Sonnet 5", "Claude Opus 5", "DeepSeek V3"],
    "thai-content": ["Gemini 2.5 Pro", "Claude Sonnet 5", "GPT-4o"],
    "research": ["DeepSeek R1", "Gemini 2.5 Pro", "Claude Opus 5"],
    "fast": ["Gemini 2.5 Flash", "DeepSeek V3", "Claude Sonnet 5"],
}

DEFAULT_CANDIDATES = ["Claude Sonnet 5", "Claude Opus 5", "DeepSeek R1"]

# Cooldown durations by failure class (minutes)
COOLDOWN_MODEL_ERROR = 15        # MODEL_ERROR / SEND_FAILED
COOLDOWN_MODEL_SWITCH_FAILED = 5  # MODEL_SWITCH_FAILED


def _default_model_entry() -> dict:
    return {
        "status": "AVAILABLE",
        "cooldownUntil": 0,
        "lastUsed": 0,
        "successCount": 0,
        "failCount": 0,
        "lastLatencySeconds": None,
    }


def load_state(state_file: str = None) -> dict:
    path = state_file or STATE_FILE
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"models": {}, "lastUpdated": 0}


def save_state(state: dict, state_file: str = None):
    path = state_file or STATE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state["lastUpdated"] = int(time.time())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_candidates_for_task(task_class: str, state_file: str = None) -> list:
    """Full ordered candidate list, cooldown-aware, for the failover loop.

    Models not on cooldown come first (in TASK_ROUTING order); cooled-down
    models are appended at the end as a last resort.
    """
    state = load_state(state_file)
    now = int(time.time())
    candidates = TASK_ROUTING.get(task_class, DEFAULT_CANDIDATES)
    available = [
        m for m in candidates
        if now >= state.get("models", {}).get(m, {}).get("cooldownUntil", 0)
    ]
    return available + [m for m in candidates if m not in available]


def set_model_cooldown(model: str, cooldown_minutes: int = COOLDOWN_MODEL_ERROR, state_file: str = None):
    """Put a model on cooldown and bump its failCount (incremental update)."""
    state = load_state(state_file)
    now = int(time.time())
    if "models" not in state:
        state["models"] = {}
    entry = state["models"].get(model, _default_model_entry())
    entry.update({
        "status": "COOLDOWN",
        "cooldownUntil": now + (cooldown_minutes * 60),
        "lastUsed": now,
        "failCount": entry.get("failCount", 0) + 1,
    })
    state["models"][model] = entry
    save_state(state, state_file)
    print(f"[COOLDOWN] Model '{model}' put on cooldown for {cooldown_minutes} minutes.")


def record_model_success(model: str, latency_seconds: float = None, state_file: str = None):
    """Record a successful run (incremental update, preserves other stats)."""
    state = load_state(state_file)
    now = int(time.time())
    if "models" not in state:
        state["models"] = {}
    entry = state["models"].get(model, _default_model_entry())
    entry.update({
        "status": "AVAILABLE",
        "cooldownUntil": 0,
        "lastUsed": now,
        "successCount": entry.get("successCount", 0) + 1,
    })
    if latency_seconds is not None:
        entry["lastLatencySeconds"] = latency_seconds
    state["models"][model] = entry
    save_state(state, state_file)


def apply_failure_cooldown(last_error: str, model: str, state_file: str = None):
    """Map a failover RuntimeError message to the right cooldown duration."""
    if "MODEL_ERROR" in last_error or "SEND_FAILED" in last_error:
        set_model_cooldown(model, COOLDOWN_MODEL_ERROR, state_file)
    elif "MODEL_SWITCH_FAILED" in last_error:
        set_model_cooldown(model, COOLDOWN_MODEL_SWITCH_FAILED, state_file)
