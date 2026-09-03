# HANDOFF.md — สถานะโปรเจกต์และแผนงานสำหรับผู้ร่วมพัฒนา (รวม AI agents)

> เอกสารนี้เขียนไว้ให้ AI หรือนักพัฒนาคนใหม่ที่มาต่องานบน repo นี้อ่านก่อนลงมือ
> อัปเดตล่าสุด: 2026-09-03 (Phase 1 Optimization เสร็จสมบูรณ์)
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
- `build_inject_script(target, message, model)` — JS ฝัง prompt ต่อแพลตฟอร์ม
- `build_content_reader_script(target)` — JS อ่านข้อความตอบ
- `execute_bridge(...)` — flow หลัก: หา tab → เชื่อม WS → inject → poll จน stabilize → เขียนไฟล์
- `main()` — argparse + exit code

## แผนที่วางไว้ต่อไป

### Phase 2 — Architecture & Features (ลำดับถัดไปที่ควรทำ)
1. **Adapter pattern** — แยก `build_inject_script` เป็นโมดูลต่อ target (`targets/copilot.py` ฯลฯ)
   + registry แบบ plug-in เพื่อเพิ่ม platform ใหม่ไม่ต้องแก้ไฟล์หลัก
2. **Streaming output จริง** — เขียน reply ลงไฟล์แบบ incremental ระหว่าง stream
   + เพิ่ม `--json` output สำหรับ pipeline
3. **Retry/resilience** — จับ rate-limit, response ค้าง, tab ถูกปิดกลางทาง (backoff + resume room เดิม)
4. **Multi-turn `chat` mode** — interactive หรืออ่าน instruction จาก stdin
5. **Test ตรรกะ JS** — selector/JS แยกเป็น template ที่ mock ได้ + smoke test กับ CDP mock server
6. **Packaging** — `pyproject.toml` + entry point (ติดตั้งด้วย pipx) + GitHub Actions (pytest + ruff)

### Phase 3 — Optional / ระยะยาว
- เพิ่ม target: ChatGPT web, Gemini, Perplexity (ผ่าน adapter จาก Phase 2)
- MCP server wrapper — ให้ AI agent เรียก bridge นี้เป็น tool โดยตรง
- Fan-out หลาย target พร้อมกัน (`ask --target all`) เพื่อเทียบคำตอบหลายโมเดล

## ข้อควรระวังสำหรับคนแก้โค้ดต่อ

- JS injection เป็น f-string — วงเล็บปีกกาต้อง escape เป็น `{{ }}` ให้ครบ
- Tests ผูกกับลำดับการเรียก `eval_js` (inject → scroll → read text สลับกัน) และข้อความใน
  copilot script (`document.execCommand('insertText'`, `aria-label*='ส่งข้อความ'`, `aria.includes('ส่ง')`)
  ถ้าแก้ flow ต้องแก้ tests คู่กัน
- การ stabilize ยังใช้ความยาวข้อความนิ่ง 3 รอบ (12 วินาที) — ถ้า platform ไหน stream ช้ามาก
  อาจ false-finish ได้ ควรยกไปใช้ indicator จริง (send button enabled / typing icon หาย) ใน Phase 2
- CDP `/json/new` ต้องใช้ HTTP PUT บน Brave/Chrome ใหม่ — อย่าเปลี่ยนกลับเป็น GET
