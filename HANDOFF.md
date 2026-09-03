# HANDOFF.md — สถานะโปรเจกต์และแผนงานสำหรับผู้ร่วมพัฒนา (รวม AI agents)

> เอกสารนี้เขียนไว้ให้ AI หรือนักพัฒนาคนใหม่ที่มาต่องานบน repo นี้อ่านก่อนลงมือ
> อัปเดตล่าสุด: 2026-09-03 (Phase 1 Optimization + merge aipass-auto-router Phase 2)
>
> **หมายเหตุการร่วมมือ:** ไฟล์ `HANDOFF_TO_ZAI.md` เขียนโดย AI อีกตัว ("Antigravity")
> ซึ่ง push งานก่อนหน้านี้ (Copilot selectors, bridge.py alias) — งานของทั้งสองฝั่ง
> ถูกรวมกันใน commit นี้แล้ว และข้อกำหนด "UI & CDP Invariants" ในไฟล์นั้นยังมีผลบังคับ

## โปรเจกต์นี้คืออะไร

Python CLI (`brave_web_ai_bridge.py`, ไฟล์เดียวจบ) ที่สั่งงานเว็บ AI chat ผ่าน Brave Browser
ที่เปิด remote debugging ไว้ (`--remote-debugging-port=9222`) โดยใช้ Chrome DevTools Protocol
ผ่าน WebSocket — ไม่ launch browser ใหม่ ใช้ session ที่ login แล้ว

เป้าหมายที่รองรับ (ดู `TARGETS` dict ในไฟล์หลัก):

| target | แพลตฟอร์ม |
|---|---|
| `copilot` | Microsoft 365 Copilot (m365.cloud.microsoft) — รองรับ room/conversation ID |
| `okmd` | OKMD AI Playground (DeepSeek, Claude, GPT, Gemini ฯลฯ) |
| `aipass` | AIPass Chat (Claude Opus 5, Sonnet 5, Gemini 3.1 Pro) |

วิธีใช้: ดู README.md หรือ SKILL.md

## ทำอะไรไปแล้ว (Phase 1 — Optimization, commit ปัจจุบัน)

1. **ไฟล์ซ้ำ `bridge.py` หมดปัญหาแล้ว** — ตอนนี้เป็น alias 5 บรรทัดที่ import จาก
   `brave_web_ai_bridge` เพื่อ backward compatibility (โค้ดจริงอยู่ที่ `brave_web_ai_bridge.py` ไฟล์เดียว)
   (ส่วนนี้ร่วมมือกับงานของ Antigravity ซึ่งทำ alias + Copilot selectors ไว้ก่อน —
   เราผสาน selector chain `button.fai-SendButton` และ AI-message isolation
   `.fai-AiMessage` เข้ากับ refactor ของเราแล้ว)
2. **เขียน CDP client ใหม่ (`BraveCdpClient`)**
   - `send_cmd` ใช้ pending-request Future + background reader task (`_read_loop`)
     แทน busy-loop เดิมที่ทิ้ง CDP events — ปลอดภัยต่อข้อความ interleave และมี timeout ต่อ command (30s)
   - `eval_js` ตรวจ `exceptionDetails` แล้ว raise `BridgeError` (เดิมคืน None เงียบ ๆ)
3. **แยก config ต่อ target เป็น `TARGETS` dict** — URL, url_match, room_url_template,
   content_selectors อยู่ที่เดียว; `--target` choices ดึงจาก dict โดยตรง
4. **เพิ่ม exit code** — CLI คืน exit 1 เมื่อ injection ล้มเหลวหรือ response ไม่ stabilize ภายใน timeout
   (เดิม silent failure); `execute_bridge` คืน `bool`
5. **แก้ bug navigation ของ Copilot room** — เดิม activate tab แต่ไม่ navigate;
   ตอนนี้ navigate จริงผ่าน `Page.navigate` หลังเชื่อม WebSocket
6. **Response reader เลือก conversation container ก่อน `document.body`**
   ต่อ target (`content_selectors`) ลด noise จาก sidebar/typing indicator (ยังมี body เป็น fallback)
7. **ตัวเลข timing รวมเป็นค่าคงที่** `CDP_CMD_TIMEOUT / TAB_OPEN_WAIT / POLL_INTERVAL / STABLE_CYCLES / MIN_RESPONSE_CHARS`

Test suite ผ่านครบ 10/10 (`pytest tests`) — ต้องติดตั้ง `requirements-test.txt`
(รวม `pytest-asyncio` ซึ่งจำเป็นแต่เดิมไม่มีในเครื่อง dev)

## โครงสร้างโค้ดสำคัญ (ใน brave_web_ai_bridge.py)

- `TARGETS` — config ต่อ platform
- `BraveCdpClient` — ต่อ CDP, `send_cmd`/`eval_js`/`press_enter`
- `AipassAdapter` — reliability layer ของ aipass (select_model + verify, send_and_verify,
  monitor_response แบบ adaptive timeout, error toast detection) — ใช้ BraveCdpClient เป็น transport
- `execute_aipass_routed(...)` — failover loop ตาม candidate list จาก router
- `router/aipass_router.py` — TASK_ROUTING, cooldown state (`state/model_status.json`),
  per-model stats (successCount/failCount/lastLatencySeconds — update แบบ incremental ไม่ทับก้อน)
- `build_inject_script(target, message, model)` — JS ฝัง prompt ต่อแพลตฟอร์ม
- `build_content_reader_script(target)` — JS อ่านข้อความตอบ
- `execute_bridge(...)` — flow หลัก: หา tab → เชื่อม WS → inject → poll จน stabilize → เขียนไฟล์
  (aipass + `--task` ไม่มี `--model` → วิ่งเข้า `execute_aipass_routed` แทน)
- `main()` — argparse + exit code (0 สำเร็จ / 1 fail / 2 router หมด candidates)

## Merged from aipass-auto-router (Phase 2 "Reliability Hardening")

ย้ายมาจาก https://github.com/tukimtk-design/aipass-auto-router (commit 6b27657, 6b5e420,
ทดสอบ live end-to-end กับ aipass.net แล้ว 2026-09-03) — โดยใช้ `BraveCdpClient` ของ repo นี้
เป็น transport ตาม Zero-Browser Rule (CDP 9222 เท่านั้น) และ backward compat 100%

1. **Send verification + retry** — นับ assistant messages ก่อน/หลังส่ง + เช็ค textarea ถูกเคลียร์
   ภายใน 8s; ไม่ผ่านจะ inject+send ใหม่สูงสุด 2 ครั้ง (`AipassAdapter.send_and_verify`)
2. **Router module (`router/aipass_router.py`)** — `TASK_ROUTING` 5 task classes → 3 candidates,
   `get_candidates_for_task()` เรียงตัวไม่ติด cooldown ก่อน, cooldown state ที่
   `state/model_status.json` (MODEL_ERROR/SEND_FAILED = 15 นาที, MODEL_SWITCH_FAILED = 5 นาที),
   failover loop จบด้วย exit code 2 เมื่อหมด list
3. **Adaptive stream timeout** — ต่อเวลา 30s เมื่อยังมี stop button, hard cap 600s รวม
   (`AipassAdapter.monitor_response`) — โมเดล reasoning ตอบยาวไม่โดนตัดกลางคัน
4. **Model switch verification** — อ่านป้ายปุ่ม (`bg-bg-input-control`) ยืนยันว่าเปลี่ยนโมเดลจริง
5. **Error toast detection กว้าง** — limit/quota/failed/unauthorized/expired + ไทย
   ("เกิดข้อผิดพลาด", "ลองอีกครั้ง") → raise MODEL_ERROR ให้ failover ต่อ

CLI: `--task <class>` ใช้กับ aipass (ไม่ระบุ `--model` = router เลือก + failover,
ระบุ `--model` = ใช้ตรง ๆ ตามเดิม) — เอกสาร: README.md

## แผนที่วางไว้ต่อไป

### Phase 2 — Architecture & Features (ลำดับถัดไปที่ควรทำ)
1. **Adapter pattern** — แยก `build_inject_script` เป็นโมดูลต่อ target (`targets/copilot.py` ฯลฯ)
   + registry แบบ plug-in เพื่อเพิ่ม platform ใหม่ไม่ต้องแก้ไฟล์หลัก
   (ผสาน `AipassAdapter` เข้าโครงสร้างนี้ด้วย)
2. **Streaming output จริง** — เขียน reply ลงไฟล์แบบ incremental ระหว่าง stream
   + เพิ่ม `--json` output สำหรับ pipeline
3. **Retry/resilience ทั่วทั้ง bridge** — aipass มี failover แล้ว (จาก merge); ขยายไป
   rate-limit/response ค้าง/tab ถูกปิดกลางทาง (backoff + resume room เดิม) ให้ copilot/okmd
4. **Multi-turn `chat` mode** — interactive หรืออ่าน instruction จาก stdin
5. **Test ตรรกะ JS** — selector/JS แยกเป็น template ที่ mock ได้ + smoke test กับ CDP mock server
6. **Packaging** — `pyproject.toml` + entry point (ติดตั้งด้วย pipx) + GitHub Actions (pytest + ruff)

### Phase 3 — Response Quality (จาก roadmap เดิมของ aipass-auto-router)
- ใช้ MutationObserver แทน polling `innerText` ทุก 1.5s → ลด latency การ detect จบ stream
- Scope การ extract ให้ fix ที่ conversation container จริง (ไม่ใช้ selector
  `div[class*="message"]` กว้าง ๆ ที่จับผิด element)
- เก็บ conversation URL/ID หลังส่ง เพื่อ resume และอ่านผลซ้ำได้

### Phase 4 — Capability Extension
- Attachment/ไฟล์: upload ผ่าน CDP `DOM.setFileInputFiles`
- Batch mode: อ่าน queue จาก JSONL, รันตามลำดับ, เขียนผลทีละแถว
- เพิ่ม target: ChatGPT web, Gemini, Perplexity (ผ่าน adapter จาก Phase 2)

### Phase 5 — Smart Routing / ระยะยาว
- Adaptive routing จากสถิติจริง (latency/success rate ที่เก็บตั้งแต่ merge Phase 2) แทน static table
- `--probe`: ยิง prompt ทดสอบสั้น ๆ เพื่อวัดความพร้อมจริงของแต่ละโมเดล
- MCP server wrapper — ให้ AI agent เรียก bridge นี้เป็น tool โดยตรง
- Fan-out หลาย target พร้อมกัน (`ask --target all`) เพื่อเทียบคำตอบหลายโมเดล

> หมายเหตุ: repo ต้นทาง `aipass-auto-router` ควรถูกแปลงเป็น SKILL wrapper ที่ชี้มาที่ repo นี้
> (อย่าลบประวัติ) — ยังเป็นงานค้าง ให้เปิด issue ใน repo นั้นเพื่อตามงาน

## ข้อควรระวังสำหรับคนแก้โค้ดต่อ

- JS injection เป็น f-string — วงเล็บปีกกาต้อง escape เป็น `{{ }}` ให้ครบ
- Tests ผูกกับลำดับการเรียก `eval_js` (inject → scroll → read text สลับกัน) และข้อความใน
  copilot script (`document.execCommand('insertText'`, `aria-label*='ส่งข้อความ'`, `aria.includes('ส่ง')`)
  ถ้าแก้ flow ต้องแก้ tests คู่กัน
- การ stabilize ยังใช้ความยาวข้อความนิ่ง 3 รอบ (12 วินาที) — ถ้า platform ไหน stream ช้ามาก
  อาจ false-finish ได้ ควรยกไปใช้ indicator จริง (send button enabled / typing icon หาย) ใน Phase 2
- CDP `/json/new` ต้องใช้ HTTP PUT บน Brave/Chrome ใหม่ — อย่าเปลี่ยนกลับเป็น GET
