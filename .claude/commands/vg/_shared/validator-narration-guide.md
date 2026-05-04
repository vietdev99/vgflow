---
name: vg:_shared:validator-narration-guide
description: Authoring guide for validator Evidence messages — mandatory human-language narration via _i18n.t() (B8.0, 2026-04-23)
---

# Validator Narration Guide — Human Language Mandatory

**User mandate (2026-04-23):** "ở tất cả các khâu, trả lời hoặc hiển thị thông tin đều phải là ngôn ngữ loài người, cố gắng giải thích cụ thể vấn đề, bằng ngôn ngữ được cài trong vg.config.md. Đây là điều bắt buộc."

Every validator that emits `Evidence(message=..., fix_hint=...)` MUST route user-visible text through `_i18n.t()` so output language follows `narration.locale` from vg.config.md. No hardcoded English literals in Evidence fields.

---

## Rule set

1. **`Evidence.message`** and **`Evidence.fix_hint`** MUST be `t(key, ...)` — never raw strings.
2. **`Evidence.actual`** stays raw — it's data (file paths, IDs, code samples), not prose.
3. **`Evidence.expected`** same — raw data or regex, not prose.
4. Every new key MUST have **BOTH** `vi` (primary) and `en` (fallback) templates. Test `test_all_validator_keys_have_both_locales` enforces this.
5. **Explain the problem concretely** — not "validation failed" but "Commit {ref} cites D-{num} which doesn't exist in {phase_dir}/CONTEXT.md".
6. **Provide actionable `fix_hint`** — specify the command, file, or decision the user must make.
7. English technical terms inside VN templates MUST have VN gloss in parentheses on first use (per `term-glossary.md` R2). Example: `validator (bộ kiểm)`, `gate (cổng chặn)`, `debt register (sổ nợ)`.

## Key naming convention

```
<validator>.<evidence_type>.<field>
```

- `<validator>` — short validator name (e.g. `commit_attr`, `contract_runtime`)
- `<evidence_type>` — matches `Evidence.type` so log aggregation ties together
- `<field>` — `message` | `fix_hint` | `summary`

Examples:
- `commit_attr.phantom_citation.message`
- `contract_runtime.missing_endpoint.fix_hint`

## How to add a new validator

### Step 1 — Import the helper

```python
# validators/my-new-validator.py
sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit
from _i18n import t  # MANDATORY — B8.0 narration rule
```

### Step 2 — Register message keys in `narration-strings-validators.yaml`

```yaml
my_validator.bad_thing.message:
  vi: "Dữ liệu {field} không hợp lệ: {value}. Expected {expected_pattern}."
  en: "Invalid {field}: {value}. Expected {expected_pattern}."

my_validator.bad_thing.fix_hint:
  vi: |
    Sửa {field} trong {file_path} để khớp pattern {expected_pattern}.
    Hoặc chạy /vg:<command> để regenerate.
  en: |
    Fix {field} in {file_path} to match pattern {expected_pattern}.
    Or run /vg:<command> to regenerate.
```

### Step 3 — Use `t()` in Evidence

```python
out.add(Evidence(
    type="bad_thing",  # matches key middle component
    message=t(
        "my_validator.bad_thing.message",
        field="email", value=user_value, expected_pattern="RFC 5322",
    ),
    actual=user_value,  # raw data — NOT translated
    fix_hint=t(
        "my_validator.bad_thing.fix_hint",
        field="email", file_path=str(cfg_path),
        expected_pattern="RFC 5322",
    ),
))
```

### Step 4 — Regression test

The test file should include:

```python
def test_my_validator_vi_output(tmp_path):
    # ... setup ...
    r = subprocess.run([...], env={**os.environ, "VG_REPO_ROOT": str(tmp_path)})
    # Assert distinctive VN markers in r.stdout
    vn_markers = ["không hợp lệ", "kh\\u00f4ng h\\u1ee3p l\\u1ec7"]
    assert any(m in r.stdout for m in vn_markers)
```

## What `t()` does under the hood

1. Read `narration.locale` + `narration.fallback_locale` from vg.config.md (cached).
2. Load + merge all `narration-strings*.yaml` in `_shared/` (cached).
3. Lookup template in `<locale>` → fallback → `en` → key literal (graceful).
4. `str.format(**kwargs)` interpolates placeholders.
5. Missing placeholder → template returned as-is (no crash).

See `.claude/scripts/validators/_i18n.py`.

## Anti-patterns to avoid

- ❌ `message="Endpoint not found"` — English literal, won't translate
- ❌ `message=f"Found {n} violations"` — string interpolation without i18n
- ❌ `message=t("my.key") + " " + file_path` — concatenation outside template (add `{file}` placeholder instead)
- ❌ Evidence.message with technical-code-only text like `"E_VALIDATION_42"` — meaningless to humans
- ❌ Adding keys without `vi` translation — breaks test_all_validator_keys_have_both_locales
- ❌ Using `en` template for `vi` until someone "gets around to translating" — write vi on day one

## Retrofit status

Validators already retrofitted (reference implementations):
- `commit-attribution.py`
- `verify-contract-runtime.py`

Pending retrofit (tracked as B8.5 follow-up, not blocking v2.4):
- `phase-exists.py`, `context-structure.py`, `plan-granularity.py`
- `task-goal-binding.py`, `override-debt-balance.py`, `test-first.py`
- `runtime-evidence.py`, `goal-coverage.py`, `deferred-evidence.py`
- `review-skip-guard.py`, `acceptance-reconciliation.py`, `event-reconciliation.py`
- `build-crossai-required.py`, `check-override-events.py`
- `vg-design-coherence.py`, `wave-attribution.py`, `verify-commit-attribution.py`

For new validators created in B8.1, B8.2, B8.3 — use this pattern from day one.
