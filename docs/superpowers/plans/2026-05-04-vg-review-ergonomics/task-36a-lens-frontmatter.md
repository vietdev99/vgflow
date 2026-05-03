<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-04-vg-review-ergonomics.md -->
<!-- Spec: docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md -->

## Task 36a: Lens prompt frontmatter migration (19 files × 6 fields)

**Files:**
- Modify: `commands/vg/_shared/lens-prompts/lens-*.md` (19 files)
- Test: `tests/test_lens_prompt_frontmatter.py`

**Why:** Task 26 shipped `lens_tier_dispatcher.py` + `emit-dispatch-plan.py` expecting per-lens frontmatter fields (recommended_worker_tier, worker_complexity_score, fallback_on_inconclusive, min_actions_floor, min_evidence_steps, required_probe_kinds). Current lens-prompt files have only the older fields (name, bug_class, applies_to_*, severity_default, estimated_action_budget, output_schema_version, runtime). Without these 6 fields, dispatcher defaults every lens to `haiku` + complexity 1 — opposite of M1 capability floor goal.

Codex round-1 finding #66 quantified: 19 files × 6 fields = **114 atomic edits**. Pure additive; no logic change.

**Field values per spec line 161-178** (Task 26 spec table). One row per lens.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lens_prompt_frontmatter.py`:

```python
"""Task 36a — verify all lens-*.md have the 6 required frontmatter fields."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
LENS_DIR = REPO / "commands/vg/_shared/lens-prompts"

REQUIRED_FIELDS = (
    "recommended_worker_tier",
    "worker_complexity_score",
    "fallback_on_inconclusive",
    "min_actions_floor",
    "min_evidence_steps",
    "required_probe_kinds",
)

VALID_TIERS = {"haiku", "sonnet", "opus", "crossai"}
VALID_FALLBACKS = {"haiku", "sonnet", "opus", "crossai", "none"}


def _load_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.+?)\n---", text, re.DOTALL)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def test_every_lens_has_all_6_fields() -> None:
    failures: list[str] = []
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        if lens_path.stem == "_TEMPLATE":
            continue
        fm = _load_frontmatter(lens_path)
        for field in REQUIRED_FIELDS:
            if field not in fm:
                failures.append(f"{lens_path.name}: missing {field}")
    assert not failures, "\n".join(failures)


def test_recommended_worker_tier_valid() -> None:
    failures: list[str] = []
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        tier = fm.get("recommended_worker_tier")
        if tier and tier not in VALID_TIERS:
            failures.append(f"{lens_path.name}: tier={tier} not in {VALID_TIERS}")
    assert not failures, "\n".join(failures)


def test_complexity_score_in_range() -> None:
    failures: list[str] = []
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        score = fm.get("worker_complexity_score")
        if score is not None and not (1 <= int(score) <= 5):
            failures.append(f"{lens_path.name}: complexity_score={score} not in 1..5")
    assert not failures, "\n".join(failures)


def test_complexity_4_requires_sonnet_plus() -> None:
    """Spec invariant: complexity ≥4 forces sonnet+; complexity ==5 forces opus."""
    failures: list[str] = []
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        score = fm.get("worker_complexity_score")
        tier = fm.get("recommended_worker_tier")
        if score == 5 and tier != "opus":
            failures.append(f"{lens_path.name}: complexity 5 requires opus, got {tier}")
        if score == 4 and tier == "haiku":
            failures.append(f"{lens_path.name}: complexity 4 forbids haiku, got {tier}")
    assert not failures, "\n".join(failures)


def test_fallback_on_inconclusive_valid() -> None:
    failures: list[str] = []
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        fb = fm.get("fallback_on_inconclusive")
        if fb and fb not in VALID_FALLBACKS:
            failures.append(f"{lens_path.name}: fallback={fb} not in {VALID_FALLBACKS}")
    assert not failures, "\n".join(failures)


def test_min_actions_floor_positive() -> None:
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        floor = fm.get("min_actions_floor")
        assert floor is None or floor >= 1, f"{lens_path.name}: min_actions_floor must be ≥1"


def test_required_probe_kinds_is_list() -> None:
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        kinds = fm.get("required_probe_kinds")
        assert kinds is None or isinstance(kinds, list), f"{lens_path.name}: required_probe_kinds must be list"
```

- [ ] **Step 2: Run failing tests**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_lens_prompt_frontmatter.py -v
```

Expected: tests fail because 19 files don't have the new fields.

- [ ] **Step 3: Apply frontmatter migrations per spec table**

Spec line 161-178 declares the per-lens values. Migration table (target frontmatter):

| Lens file | tier | complexity | min_actions | min_evidence | fallback | probe_kinds |
|---|---|---|---|---|---|---|
| lens-info-disclosure | haiku | 2 | 5 | 3 | sonnet | [stack_trace, dotfile_probe, debug_route] |
| lens-csrf | haiku | 2 | 4 | 3 | sonnet | [token_missing, samesite_probe, cors_credentialed] |
| lens-input-injection | haiku | 2 | 6 | 4 | sonnet | [xss_form_field, sql_injection, template_injection] |
| lens-modal-state | sonnet | 3 | 8 | 5 | opus | [esc_dismiss, focus_trap, multi_modal_stack] |
| lens-form-lifecycle | sonnet | 4 | 10 | 8 | opus | [create_then_read, update_then_read, delete_then_read] |
| lens-business-coherence | sonnet | 4 | 8 | 6 | opus | [ui_vs_network, network_vs_db, console_vs_state] |
| lens-idor | sonnet | 3 | 8 | 6 | opus | [horizontal_id_swap, vertical_role_swap, peer_tenant_replay] |
| lens-bfla | sonnet | 3 | 8 | 6 | opus | [admin_endpoint_from_user, verb_drift, action_field_bypass] |
| lens-tenant-boundary | sonnet | 4 | 10 | 8 | opus | [cross_tenant_id_swap, audit_log_leak, expand_param] |
| lens-auth-jwt | sonnet | 3 | 6 | 5 | opus | [alg_confusion, alg_none, kid_injection] |
| lens-business-logic | opus | 5 | 12 | 10 | crossai | [state_machine_bypass, currency_rounding, quota_slicing] |
| lens-mass-assignment | sonnet | 3 | 6 | 5 | opus | [is_admin_append, tenant_id_append, role_field_probe] |
| lens-ssrf | haiku | 2 | 5 | 4 | sonnet | [internal_url, cloud_metadata, dns_rebinding] |
| lens-open-redirect | haiku | 2 | 5 | 4 | sonnet | [scheme_trick, encoding_bypass, fragment_confusion] |
| lens-path-traversal | haiku | 2 | 5 | 4 | sonnet | [parent_dir_escape, encoded_traversal, zip_slip] |
| lens-file-upload | haiku | 2 | 6 | 4 | sonnet | [polyglot_file, double_extension, htaccess_override] |
| lens-duplicate-submit | sonnet | 4 | 8 | 6 | opus | [parallel_http2, idempotency_reuse, last_byte_sync] |
| lens-table-interaction | haiku | 2 | 6 | 4 | sonnet | [filter_pre_post, sort_pre_post, paginate_pre_post] |
| lens-authz-negative | sonnet | 3 | 8 | 6 | opus | [wrong_role, unauth, peer_tenant_attempt] |

For each lens file, edit the frontmatter to add the 6 fields. Example for `lens-form-lifecycle.md`:

```yaml
---
name: lens-form-lifecycle
description: ...existing...
bug_class: state-coherence
applies_to_element_classes: [form]
applies_to_phase_profiles: [web-fullstack, web-frontend-only]
severity_default: warn
estimated_action_budget: 25
output_schema_version: 3
runtime: review

# Task 26 / Task 36a additions:
recommended_worker_tier: sonnet
worker_complexity_score: 4
fallback_on_inconclusive: opus
min_actions_floor: 10
min_evidence_steps: 8
required_probe_kinds: [create_then_read, update_then_read, delete_then_read]
---
```

Apply to all 19 files. **Atomic commit** — one PR for all 19 to keep migration auditable.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_lens_prompt_frontmatter.py -v
```

Expected: 7 PASSed.

- [ ] **Step 5: Commit**

```bash
DEV_ROOT=. bash sync.sh --no-global 2>&1 | tail -3
git add commands/vg/_shared/lens-prompts/lens-*.md \
        tests/test_lens_prompt_frontmatter.py \
        .claude/ codex-skills/ .codex/
git commit -m "feat(lens-enforcement): add tier + complexity + probe-kinds frontmatter to 19 lens prompts (Task 36a, Bug D part 1)

Task 26 shipped lens_tier_dispatcher.py + emit-dispatch-plan.py expecting
per-lens frontmatter fields, but current lens-prompt files only have
legacy fields (name, bug_class, applies_to_*). Without the 6 new fields
(recommended_worker_tier, worker_complexity_score, fallback_on_inconclusive,
min_actions_floor, min_evidence_steps, required_probe_kinds) the
dispatcher defaults every lens to haiku + complexity 1 — opposite of
M1 capability floor.

114 atomic edits (19 files × 6 fields). Pure additive, no logic change.
Values per Task 26 spec table. Codex round-1 finding #66 isolated this
as separate task from 36b wiring (architectural cost).

Test invariants verified:
- All 19 files have all 6 fields
- recommended_worker_tier ∈ {haiku, sonnet, opus, crossai}
- worker_complexity_score ∈ 1..5
- complexity 5 ⇒ opus tier
- complexity 4 ⇒ NOT haiku tier (sonnet+)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
