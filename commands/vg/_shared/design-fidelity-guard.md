---
name: vg:_shared:design-fidelity-guard
description: Design Fidelity Guard (Shared Reference) — spawns isolated Haiku subagent with zero parent context to compare a UI commit diff against the design PNG. Catches semantic-level drift that pixel-diff (L3/L4) and structural validators (L2) miss.
---

# Design Fidelity Guard — Shared Helper (P19 D-05 — Lớp 5)

Pixel-level gates (L3 build-visual, L4 review SSIM) catch geometric drift. Structural gates (L2 fingerprint) catch missing sections in the executor's pre-code description. Neither catches **AI shipped code that doesn't match the design at semantic level** — e.g. correct grid count, but wrong components in the cells; correct fingerprint description, but actual JSX uses generic divs. This guard closes that gap.

## Why this layer exists

After v2.13.0 four-layer pipeline + L-002 mandate, the residual failure mode is:
- AI reads PNG (or claims it did)
- AI writes LAYOUT-FINGERPRINT.md describing what it "saw"
- AI ships JSX that **passes pixel diff** (because both sides happen to be a centered card) but **misses every component** the design called for (Sidebar, TopBar, KPICards, etc.)

L3 SSIM pass + L2 fingerprint pass + L4 SSIM pass — yet UI is wrong. The gap: nobody verified **what the code shipped corresponds to what the PNG shows at component level**.

## Mechanism: separate-model adjudication

Same root principle as `rationalization-guard.md`: avoid same-model echo chamber. Spawn a fresh **Haiku** subagent with:
- The PNG (Read tool, vision-capable model sees pixels)
- The git diff for the task commit
- The slug's row from `VIEW-COMPONENTS.md` if present (D-02 output) — list of expected components

The subagent has zero parent context — cannot rationalize "but the executor said it would". It compares: *do the components I see in the PNG appear, by name/className/role, in the diff?*

## API

```
design_fidelity_guard_check(phase_dir, task_num, slug, commit_sha) → {verdict, reason, missing_components, confidence}
```

Returns single-line JSON to stdout:
- `verdict`: `"PASS"` | `"FLAG"` | `"BLOCK"`
- `reason`: ≤200 chars
- `missing_components`: array of component names (semantic, e.g. "Sidebar", "TopBar", not "div")
- `confidence`: `"low"` | `"medium"` | `"high"`

### Caller contract

| Verdict | Meaning | Caller action |
|---------|---------|---------------|
| `PASS` | Every expected component appears in diff (by tag, className, role, or text) | Continue. |
| `FLAG` | 1-2 minor components missing OR uncertainty | Continue, log override-debt `kind=design-fidelity-flag` severity:medium. |
| `BLOCK` | ≥3 missing OR a core component (Sidebar/TopBar/MainContent) absent | Fail wave gate. Override `--allow-vision-self-verify-fail` + rationalization-guard. |

## Implementation

The shipping script is `scripts/validators/verify-vision-self-verify.py`. It:
1. Opens the slug's PNG (`${design_dir}/screenshots/{slug}.default.png`).
2. Reads `git show {commit_sha}` for the task's diff body (FE files only).
3. Reads the slug's row from `${PHASE_DIR}/VIEW-COMPONENTS.md` if it exists (D-02 output); otherwise leaves `expected_components` as "not provided — adjudicate from PNG alone".
4. Spawns `claude --model claude-haiku-4-5-20251001 --print --no-history` with a compact prompt that injects:
   - Image attachment (PNG)
   - Diff text (truncated to 4KB)
   - VIEW-COMPONENTS row (if any)
5. Parses the single-line JSON response.
6. Emits telemetry + override-debt entry as appropriate.

**SKIP conditions** (graceful degradation, never block on harness gaps):
- `claude` CLI not on PATH → SKIP with reason
- Slug PNG missing → SKIP (L1 gate should have caught this earlier)
- Commit empty / no FE files in diff → SKIP
- Haiku spawn timeout > 30s → SKIP with telemetry warn

## Config

```yaml
visual_checks:
  vision_self_verify:
    enabled: false                  # opt-in default; flip true after dogfood
    model: "claude-haiku-4-5-20251001"
    timeout_s: 30
    block_on_core_missing: true     # core = Sidebar/TopBar/MainContent
    flag_on_minor_missing_count: 2  # 1-2 minor missing = FLAG; 3+ = BLOCK
```

## Telemetry events

- `design_fidelity_guard_pass`: `{phase, task, slug, missing_count: 0}`
- `design_fidelity_guard_flag`: `{phase, task, slug, missing: [...], override_debt_logged: true}`
- `design_fidelity_guard_block`: `{phase, task, slug, missing: [...]}`
- `design_fidelity_guard_skip`: `{phase, task, slug, reason}`

## Why not just trust L3/L4 SSIM?

SSIM is geometric (pixels); component identity is semantic. A `<main className="flex items-center">` with a centered logo can SSIM 92% against a PNG showing exactly one centered logo — even when the PNG actually shows a Sidebar+TopBar+ContentGrid that the AI quietly cropped to "the simplest interpretation". Pixel-similar ≠ semantically right. This guard is the semantic backstop.
