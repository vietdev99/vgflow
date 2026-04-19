---
name: vg:_shared:term-glossary
description: Term Glossary (Shared Reference) — RULE và bảng tra cứu giải thích thuật ngữ tiếng Anh khi narration tiếng Việt. Áp dụng mọi command có user-facing output.
---

# Term Glossary — Shared Helper

## RULE v1.14.0+ (BẮT BUỘC — Việt hoá mặc định)

**Lý do nâng cấp (2026-04-18):** Rule cũ (EN + giải thích VN ngoặc) vẫn làm output đầy thuật ngữ EN cố định khó đọc. User feedback: "Verdict, Audit, Regression ... rất nhiều khái niệm làm user mơ hồ".

**Quy tắc mới (v1.14.0+):**

Khi VG command xuất output cho user (narration, status, phán quyết, thông báo lỗi, tóm tắt, log, report, CHANGELOG entry):

**Thuật ngữ EN cố định (khái niệm, trạng thái, động từ quy trình) PHẢI dùng tiếng Việt. EN chỉ xuất hiện trong ngoặc nếu là identifier quen thuộc cần reference.**

Phân loại:

| Loại | Xử lý | Ví dụ đúng |
|---|---|---|
| Trạng thái / phán quyết (status, verdict) | **VN bắt buộc** — EN có thể đi kèm trong ngoặc lần đầu | `Kết quả: ĐẠT (PASSED)`, `Trạng thái: BỊ CHẶN`, `Phán quyết: HOÃN` |
| Động từ quy trình (audit, review, deploy, build, test) | **VN bắt buộc** | `rà soát`, `kiểm thử`, `triển khai`, `xây dựng` |
| Khái niệm workflow (scope, gate, blueprint, runbook, checkpoint, regression) | **VN bắt buộc** | `phạm vi`, `cổng kiểm tra`, `bản thiết kế`, `sổ tay triển khai`, `mốc kiểm tra`, `hồi quy` |
| Tên command (`/vg:review`, `/vg:test`) | **Giữ EN** — là tên lệnh, không dịch | `/vg:review`, `--browser-only` |
| Tên file/artifact (SPECS.md, PLAN.md) | **Giữ EN** — là ID file | `SPECS.md`, `GOAL-COVERAGE-MATRIX.md` |
| Code identifier (`D-XX`, `G-XX`, `npm`, `git`) | **Giữ EN** — là ID kỹ thuật | `D-01`, `G-05`, `git commit` |
| Format/protocol (JSON, YAML, HTTP, API) | **Giữ EN** — chuẩn ngành | `JSON`, `HTTP 200`, `API endpoint` |
| Thuật ngữ lập trình chung (function, variable, commit, branch) | **Giữ EN** — chuẩn ngành | `function`, `commit`, `branch` |

**Ví dụ so sánh (cùng thông tin, trình bày khác):**

Sai (v1.13 legacy style — EN primary):
```
BLOCKER — /vg:test 07.13 cannot run
Root cause: RUNTIME-MAP.json goal_sequences 0 entries.
Verdict: BLOCKED
Next: run /vg:review 07.13 --retry-failed
```

Đúng (v1.14+ VN-first style):
```
CHẶN — /vg:test 07.13 không chạy được
Nguyên nhân: RUNTIME-MAP.json thiếu goal_sequences (0 mục).
Kết quả: BỊ CHẶN
Bước tiếp: chạy /vg:review 07.13 --retry-failed
```

**Enforcement:**
- Lint script `.claude/scripts/vg_lang_lint.py` grep forbidden EN terms (Verdict/Audit/Regression/Blueprint/Scope/Gate/Checkpoint/Blocked/Deferred/Rollback/Runbook/...) trong command output strings
- Nếu xuất hiện ngoài context cho phép (command ID, file name, format identifier) → warn hoặc fail commit-msg hook
- Commands v1.14.0+ phải pass lint; legacy commands (v1.13 và trước) chưa bắt buộc nhưng nên sweep

**Migration path:**  
Commands cũ (viết theo rule v1.13 cũ "EN + VN ngoặc") vẫn hoạt động, nhưng sweep phải làm trong step 18 của plan implementation v1.14.0.

---

## RULE cũ (v1.13 legacy — DEPRECATED, giữ cho reference)

Khi VG command xuất output cho user (narration, status, error message, summary, log file, UAT report, CHANGELOG entry):

**Mọi thuật ngữ tiếng Anh — MUST có giải thích tiếng Việt trong dấu ngoặc đơn ở lần xuất hiện ĐẦU TIÊN trong cùng message/section.**

Ví dụ:
- ❌ Sai: `Goal G-05 status: BLOCKED — required dependency missing`
- ✅ Đúng: `Goal G-05 status: BLOCKED (bị chặn) — required dependency missing (thiếu dependency yêu cầu)`

- ❌ Sai: `Foundation drift detected — phase wording suggests platform shift`
- ✅ Đúng: `Foundation (nền tảng) drift detected (lệch hướng phát hiện) — phase wording suggests platform shift (gợi ý đổi nền tảng)`

- ❌ Sai: `State: legacy-v1 — recommend [m] Migrate`
- ✅ Đúng: `State (trạng thái): legacy-v1 (định dạng cũ v1) — recommend [m] Migrate (đề xuất chuyển đổi)`

**Lý do:** User Việt Nam đọc output workflow nhiều lần phải đoán nghĩa. Việc giải thích trong ngoặc giúp:
- User mới biết chuyện gì đang xảy ra
- Đọc lịch sử log dễ hiểu hơn
- Discussion/UAT artifact đọc được bởi non-technical stakeholders

**KHÔNG áp dụng:**
- Tên file/path (vd `PROJECT.md`, `${PLANNING_DIR}/`)
- Code identifiers (vd `D-XX`, `G-XX`, `npm`, `pnpm`, `git`, `bash`)
- Tag values từ config (vd `web-saas`, `monolith`)
- Lần lặp lại trong cùng message — chỉ cần giải thích lần đầu
- Output tiếng Anh thuần (vd file CHANGELOG bằng EN)

## Glossary — thuật ngữ phổ biến

### Pipeline state / verdicts

| EN | VN giải thích |
|----|---------------|
| BLOCK / BLOCKED | chặn / bị chặn |
| PASS / PASSED | đạt / vượt qua |
| FAIL / FAILED | thất bại / không đạt |
| READY | sẵn sàng |
| UNREACHABLE | không tiếp cận được |
| INFRA_PENDING | chờ hạ tầng |
| NOT_SCANNED | chưa quét |
| GAPS_FOUND | có lỗ hổng |
| ACCEPTED | đã chấp nhận |
| REJECTED | bị từ chối |
| DEFERRED | tạm hoãn |
| PARTIAL | một phần |
| BUG | lỗi |

### Foundation states

| EN | VN giải thích |
|----|---------------|
| greenfield | dự án mới (chưa có gì) |
| greenfield-with-docs | dự án mới có sẵn docs |
| brownfield-fresh | dự án cũ chưa có planning |
| brownfield-with-docs | dự án cũ có docs |
| legacy-v1 | định dạng cũ v1 |
| fully-initialized | đã khởi tạo đầy đủ |
| draft-in-progress | bản nháp đang chạy |
| cross-phase | liên phase (giữa nhiều phase) |
| cross-phase-pending | liên phase, chờ owner accept |
| bug-this-phase | bug thuộc phase này |
| scope-amend | cần sửa phạm vi |

### Workflow / structure

| EN | VN giải thích |
|----|---------------|
| foundation | nền tảng |
| drift | lệch hướng |
| migration / migrate | chuyển đổi |
| rewrite | viết lại |
| update | cập nhật |
| merge | gộp |
| overwrite | ghi đè |
| artifact | file kết quả |
| gate | cổng kiểm tra |
| hard gate | cổng cứng (chặn hẳn) |
| soft warning | cảnh báo nhẹ |
| override | bỏ qua rule |
| atomic | một lần all-or-nothing |
| rollback | quay lại |
| backup | sao lưu |
| staging | chỗ tạm |
| preserve | giữ nguyên |
| cascade | lan tỏa |
| scope | phạm vi |
| triage | phân loại |
| draft | bản nháp |
| resume | tiếp tục |
| discard | bỏ |
| auto-detect | tự nhận diện |
| auto-derive | tự suy ra |
| auto-fill | tự điền |
| dependency | phụ thuộc |
| precondition | điều kiện trước |
| postcondition | điều kiện sau |
| checkpoint | điểm lưu |

### Tech / architecture

| EN | VN giải thích |
|----|---------------|
| monorepo | repo gộp nhiều package |
| serverless | không server (cloud function) |
| mobile-cross | mobile đa nền tảng |
| VPS | server riêng |
| BaaS | backend dịch vụ sẵn |
| SPA | single-page app |
| SSR | render phía server |
| RTB | real-time bidding (đấu giá thời gian thực) |
| auth | xác thực |
| OAuth | xác thực qua bên thứ 3 |
| compliance | tuân thủ pháp lý |
| edge function | function ở CDN |
| stack | bộ công nghệ |

### Test / verification

| EN | VN giải thích |
|----|---------------|
| regression | hồi quy (code cũ bị break) |
| coverage | độ phủ |
| E2E (end-to-end) | từ đầu đến cuối |
| smoke test | kiểm tra cơ bản |
| mock | giả lập |
| fixture | dữ liệu mẫu |
| assertion | khẳng định kiểm tra |
| flaky | không ổn định (lúc pass lúc fail) |
| codegen | sinh code tự động |

### Identifiers (giải thích lần đầu)

| EN | VN giải thích |
|----|---------------|
| D-XX | decision (quyết định) số XX |
| G-XX | goal (mục tiêu) số XX |
| Q-XX | question (câu hỏi) số XX |
| REQ-XX | requirement (yêu cầu) số XX |
| Phase X.Y | phase (giai đoạn) X.Y |
| Wave N | wave (đợt thực thi song song) N |
| Round N | round (vòng thảo luận) N |

### Action verbs / UI

| EN | VN giải thích |
|----|---------------|
| spawn | khởi/sinh ra |
| dispatch | điều phối |
| invoke | gọi/kích hoạt |
| route | định tuyến |
| redirect | chuyển hướng |
| confirm | xác nhận |
| acknowledge | thừa nhận |
| accept | chấp nhận |
| reject | từ chối |
| defer | hoãn |
| skip | bỏ qua |
| resume | tiếp tục |
| revert | hoàn tác |

## Implementation guidance

### Trong NARRATION_POLICY của command file

Mỗi command file (review.md/test.md/build.md/project.md/accept.md) phải thêm rule này vào NARRATION_POLICY block:

```
5. **Translate English terms (RULE)** — output có thuật ngữ tiếng Anh PHẢI thêm giải thích VN trong dấu ngoặc tại lần đầu xuất hiện. Tham khảo `_shared/term-glossary.md` cho danh sách phổ biến.
   Ví dụ: `BLOCK (chặn)`, `Foundation (nền tảng) drift detected (phát hiện lệch hướng)`.
   Không áp dụng cho: file path, code identifiers, config tag values, lần lặp lại trong cùng message.
```

### Trong AskUserQuestion

Câu hỏi tiếng Việt cho user vẫn dùng template thông thường, nhưng options/labels có thuật ngữ tiếng Anh phải gloss:

```
"Bạn muốn:
 [v] View (xem)            — In hiện trạng, không đổi gì
 [u] Update (cập nhật)     — Discussion bổ sung, MERGE (gộp) giữ phần không touch
 [m] Milestone (mốc lớn)   — Append (thêm) milestone mới
 [w] Rewrite (viết lại)    — Reset toàn bộ"
```

### Trong UAT.md / SUMMARY.md / log files

File output cũng tuân theo rule. UAT.md sinh bằng tiếng Việt → mọi term tiếng Anh có gloss. CHANGELOG.md tiếng Anh thuần thì không cần (audience là dev quốc tế).

### AI agent generated text (subagent narration)

Khi orchestrator spawn subagent (Task tool) sinh narration cho user, rule cũng áp dụng. Prompt subagent phải bao gồm hint:
> Output user-facing text bằng tiếng Việt; thuật ngữ tiếng Anh phải có gloss VN trong ngoặc lần đầu xuất hiện. Tham khảo `_shared/term-glossary.md`.

## Success criteria

- Output user-facing của review/test/build/project/accept/scope đều tuân rule
- Glossary file maintained — thêm term mới khi gặp trong workflow
- AI agents (subagents) cũng follow khi orchestrator pass instruction
- File path / code identifier / config tag NOT glossed (tránh noise)
- UAT.md / log files cũng follow nếu nội dung là tiếng Việt
