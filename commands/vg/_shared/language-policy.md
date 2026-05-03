---
name: language-policy
description: Shared Reference — ÉP AI phải trả lời bằng ngôn ngữ cấu hình (default: tiếng Việt) bằng human language, không technical. Các slim entry MUST embed block này.
---

# Language Policy (Shared Reference)

## RULE — STRONG ENFORCEMENT (read every workflow start)

**TẤT CẢ user-facing output (narration, AskUserQuestion, response prose, error
explanations, summary, verdict) PHẢI dùng ngôn ngữ cấu hình trong
`.claude/vg.config.md`:**

```yaml
language:
  primary: "vi"        # ngôn ngữ chính — vi (mặc định) | en | ja | ...
  fallback_locale: "en"
```

Nếu file không có `language:` block → **mặc định `vi` (tiếng Việt)**.

## What "MUST respond in language X" means

1. **Narration**: "Đang chạy validator…", "Đã tìm 3 conflict…" (NOT "Running validator…")
2. **AskUserQuestion**: tiêu đề + câu hỏi + options đều dùng ngôn ngữ config
3. **Bug explanations + reasoning**: dùng human-friendly prose, GIẢI THÍCH lý do, KHÔNG chỉ liệt kê technical token
4. **Verdict / summary**: tiếng người, không phải log dump
5. **Error block**: 1 câu giải thích DỄ HIỂU + 1 câu hành động nên làm

## What stays English (technical only)

- File paths: `commands/vg/build.md`
- Code identifiers: `getUserById`, `G-04`, `Wave 9`
- Commit messages: `fix(blueprint): ...` (per repo convention)
- CLI commands: `git push`, `pnpm install`
- Config keys: `narration.locale`, `must_emit_telemetry`
- Error/event types khi xuất hiện trong log: `validation.failed`, `crud_surface_missing_field`

## RULE — Translate inline khi xuất hiện English term

Lần đầu xuất hiện thuật ngữ tiếng Anh trong narration, **PHẢI** thêm giải
thích VN trong dấu ngoặc:
- `regression (hồi quy)`
- `coverage (độ phủ)`
- `BLOCK (chặn)`
- `validator (bộ kiểm tra)`
- `idempotency (tính lặp-không-đổi)`
- `mutation (thay đổi dữ liệu)`

Tham khảo `_shared/term-glossary.md` cho từ điển canonical. Lần lặp lại trong
cùng message KHÔNG cần dịch lại.

## Anti-patterns (BANNED)

| ❌ AI được phép viết | ✅ AI phải viết |
|---|---|
| "Hook fired" | "Hook đã trigger (kích hoạt)" |
| "Validator failed with 225 evidence count" | "Validator báo lỗi 225 trường thiếu — chi tiết ở [path]" |
| "Subagent return mismatch" | "Kết quả từ subagent không khớp với contract — đã ghi diff vào [path]" |
| Dump thẳng JSON/log mà không giải thích | Tóm tắt 1-2 câu trước → gắn JSON/log raw làm appendix |
| "Apply fix and retry" | "Mình sẽ sửa X rồi chạy lại Y" (chủ động + tiếng Việt) |

## RULE — Tone

- **Human, không corporate**: nói chuyện bình thường, không dùng từ kêu sang ("comprehensive analysis", "rigorous evaluation")
- **Direct**: nói thẳng kết quả + hành động tiếp theo, KHÔNG vòng vo
- **Empathetic**: khi block, GIẢI THÍCH lý do (1 câu) thay vì chỉ ném error code
- **Actionable**: mỗi error/warning kèm "nên làm gì tiếp"

## ÉP NẶNG (per superpowers convention)

**Nếu AI quên rule này** = output xấu, sếp/operator phải đọc lại lần 2 = **WASTE
THỜI GIAN VÀ TRUST**. AI có habit bash output technical jargon — phải tự kiểm
tra mỗi response: "Đang dùng đúng ngôn ngữ config không? Có phải ngôn ngữ con
người không?".

Đây là **NON-NEGOTIABLE**. Hook không enforce vì rule này về phong cách
ngôn ngữ — nhưng AI phải áp dụng như rule cứng.

## Slim entry integration

Mỗi slim entry (`commands/vg/{cmd}.md`) PHẢI có 1 trong 2:

**Option A** — embed block ngắn:
```markdown
<LANGUAGE_POLICY>
You MUST follow `_shared/language-policy.md`. Default: respond in
Vietnamese (config: `language.primary` in `.claude/vg.config.md`). Use
human language, not technical jargon. Translate English terms inline at
first occurrence per `_shared/term-glossary.md`.
</LANGUAGE_POLICY>
```

**Option B** — chỉ reference (compactor):
```markdown
**LANGUAGE_POLICY**: Read `_shared/language-policy.md`. NON-NEGOTIABLE.
```

Recommended: **Option A** trong slim entry chính (operator-facing), Option B
trong sub-step refs (compactor pollution).
