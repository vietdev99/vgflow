# Dùng Claude Fable 5 với VGFlow

Date: 2026-06-12
Model: `claude-fable-5` (Anthropic, released 2026-06-09) — Mythos-class,
code-specialist. SWE-Bench Pro 80.3% (vs Opus 4.8 69.2%), 1M context, giá
$10/$50 per Mtok in/out. Refs: anthropic.com/news/claude-fable-5-mythos-5.

## TL;DR

VGFlow gắn model qua **3 đường khác nhau**. Fable 5 chạy được 2 trong 3.
Đường spawn subagent (build executor) bị Claude Code harness khóa enum —
KHÔNG phải giới hạn của VGFlow, mà của Agent tool.

| Đường | Cơ chế | Fable 5? | Bước dùng |
|---|---|---|---|
| #1 Parent/session model | model session đang chạy | ✅ chọn lúc launch | scope, blueprint orchestration, **narrative (STEP 4.5)**, accept, review orchestration |
| #2 Spawned subagent | `Agent(model=...)` | ❌ enum-locked | build executor/debugger, blueprint planner/contract_gen, test_codegen |
| #3 CLI-pipe | `claude --model X -p` | ⚠ không enum, NHƯNG cần account access | CrossAI lane (scope/blueprint/build) |

## Đường #1 — Parent model (KHÔNG sửa code)

Các bước "no agent spawn" chạy trên parent model. Launch session trên Fable 5
→ chúng tự dùng Fable, zero config.

**Cách dùng:**
- Claude Code: chọn model = Fable 5 cho session (CLI `--model claude-fable-5`
  hoặc `/model` trong session, tùy build CC của bạn).
- Các lệnh hưởng lợi nhiều nhất từ Fable trên parent:
  - `/vg:scope` — 5 rounds + deep probe + adversarial reasoning
  - **`/vg:scope` STEP 4.5 (NARRATIVE.md)** — sinh câu chuyện nghiệp vụ; Fable
    kể chuyện code-domain chính xác hơn
  - `/vg:blueprint` orchestration (phần parent, không phải planner subagent)
  - `/vg:review` orchestration + `/vg:accept`

Đây là cách dùng Fable cho **công việc code-heavy NGAY HÔM NAY** mà không vỡ gì.

## Đường #3 — CrossAI CLI-pipe (gated bởi account access)

`crossai_clis` trong `.claude/vg.config.md` shell-out qua `claude` CLI, nhận
full API model id (KHÔNG enum-lock). Đây là đường DUY NHẤT có thể đưa Fable
vào 1 subagent-style step mà không cần harness mở enum.

**NHƯNG có gate thật: account/CLI phải resolve được model id.** Verify ngày
2026-06-12 trên máy dev này:

```
$ echo ping | claude --model claude-fable-5 -p "reply OK"
There's an issue with the selected model (claude-fable-5). It may not exist
or you may not have access to it.
```

→ CLI máy này CHƯA có access. Vì vậy template GIỮ `--model sonnet` làm default
(lane luôn chạy được), kèm comment chỉ cách bật khi có access:

```yaml
crossai_clis:
  - name: "Claude"
    command: 'cat {context} | claude --model sonnet -p "{prompt}"'
    label: "Claude Sonnet 4.6"
    # ➜ verify access rồi đổi --model thành claude-fable-5
```

**Đừng hardcode `claude-fable-5` khi chưa verify** — CLI không có access sẽ
fail lane này mỗi lần CrossAI chạy (regression). Verify trước:

```bash
echo ping | claude --model claude-fable-5 -p "reply OK"
# trả OK → đổi command sang --model claude-fable-5
```

## Đường #2 — Spawned subagent (BỊ CHẶN — đừng đổi)

⚠ **KHÔNG** set `models.executor: "claude-fable-5"` (hay bất kỳ role nào trong
`models:`) trong `.claude/vg.config.md`.

Lý do: các key này feed thẳng vào `Agent(model=...)` cho subagent spawn. Agent
tool của Claude Code hiện enum-lock `sonnet|opus|haiku` và TỪ CHỐI
`claude-fable-5`:

```
InputValidationError: Invalid option: expected one of "sonnet"|"opus"|"haiku"
```

Set fable vào đó → mọi build wave spawn fail → build vỡ.

**Khi nào mở được:** khi Claude Code core thêm fable vào Agent enum (hoặc thêm
alias-resolver). Việc này ngoài tầm repo VGFlow. Tới lúc đó, build executor giữ
`sonnet` — và bạn vẫn được Fable trên parent (đường #1) cho phần reasoning.

**Nếu muốn ép Fable vào build trước khi harness mở enum:** phải refactor build
steps từ `Agent(subagent_type=..., model=...)` sang CLI-pipe
`claude --model claude-fable-5 -p`. Đánh đổi: mất khả năng spawn song song của
Agent tool (waves chạy tuần tự qua CLI). Chưa làm — chờ harness.

## Kiểm tra nhanh

```bash
# Đường #3 hoạt động? (claude CLI resolve fable chưa)
echo "ping" | claude --model claude-fable-5 -p "reply OK" 2>&1 | head -1

# Đường #2 vẫn chặn? (kỳ vọng InputValidationError — đừng dùng fable ở models:)
# Test bằng cách spawn 1 Agent(model="claude-fable-5") — sẽ báo enum error.
```

## Tóm lại nên làm gì

1. **Code-heavy reasoning** (scope/blueprint think/narrative/review): launch
   session trên Fable 5. Không sửa config.
2. **CrossAI second opinion**: verify `claude --model claude-fable-5` có
   access chưa → có thì đổi crossai_clis Claude lane. Chưa thì để sonnet.
3. **Build executor**: để `sonnet`. Chờ harness mở Agent enum cho fable.

## Trạng thái (2026-06-12)

- Đường #1 (parent): ✅ sẵn sàng — launch session trên Fable 5.
- Đường #3 (CrossAI CLI): ⚠ gated — `claude` CLI máy dev CHƯA resolve
  `claude-fable-5`. Template để sonnet + comment hướng dẫn bật.
- Đường #2 (build spawn): ❌ chặn bởi Agent enum harness. Ngoài tầm VGFlow.
