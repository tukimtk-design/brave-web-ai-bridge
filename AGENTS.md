# AGENTS.md - Instruction Charter for brave-web-ai-bridge

## Project Scope & Constraints
rave-web-ai-bridge is a Python zero-browser WebSocket Chrome DevTools Protocol (CDP) bridge connecting to Brave Browser on port 9222.

## Key Rules & Invariants
1. **Zero-Browser Rule:** Never launch Selenium, Playwright, or new browser windows. Connect to localhost:9222 via WebSocket CDP only.
2. **Single Core Library:** Core implementation resides in rave_web_ai_bridge.py. ridge.py is a 100% backwards-compatible entry alias.
3. **Mocking in Tests:** Cloud tests (e.g. Google Jules VM) must use mock WebSocket servers (	ests/test_mock_cdp.py) and never attempt live browser connections.
4. **All Tests Pass:** All pytest cases in 	ests/ must achieve 100% PASS before committing.
