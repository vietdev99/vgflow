# review runtime checks — static (declaration + file-scan validators)

Sub-refs of `runtime-checks.md`. These two sub-steps run BEFORE the
dynamic browser/device probes — they validate static declarations and
file-level scans (no MCP browser session needed).

Sub-steps in this file:
- `phase2_exploration_limits` — R8 enforcement: count actions/views/wall-time, WARN-only, write to PIPELINE-STATE.json
- `phase2_7_url_state_sync` — verify every list/table/grid goal in TEST-GOALS.md declares `interactive_controls` block; CRUD-SURFACES.md precheck included

Both sub-steps emit `mark_step` + `vg-orchestrator mark-step` lifecycle
calls — preserved verbatim from the pre-split file.

Profile: `web-fullstack` and `web-frontend-only`. Skip silently for
mobile/backend-only profiles (mobile substitutes its own discovery; backend has no UI).

---

<step name="phase2_exploration_limits" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2-limit: EXPLORATION LIMIT CHECK (R8 enforcement — v1.14.4+)

Counts actions + views + wall-time sau Phase 2 để phát hiện runaway discovery (phát hiện quét vô kiểm soát). WARN (cảnh báo) only — không block (không chặn) vì discovery đã xong. Kết quả ghi vào PIPELINE-STATE.json metrics để test/accept biết RUNTIME-MAP có thể noisy (nhiễu).

**Thresholds (ngưỡng):**
- `config.review.max_actions_per_view` — default 50
- `config.review.max_actions_total` — default 200
- `config.review.max_wall_minutes` — default 30

```bash
RUNTIME_MAP="${PHASE_DIR}/RUNTIME-MAP.json"
if [ ! -f "$RUNTIME_MAP" ]; then
  echo "⚠ RUNTIME-MAP.json chưa tồn tại — bỏ qua limit check (Phase 2 có thể skipped hoặc failed)."
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_exploration_limits" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_exploration_limits.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2_exploration_limits 2>/dev/null || true
else
  MAX_VIEW="${CONFIG_REVIEW_MAX_ACTIONS_PER_VIEW:-50}"
  MAX_TOTAL="${CONFIG_REVIEW_MAX_ACTIONS_TOTAL:-200}"
  MAX_WALL="${CONFIG_REVIEW_MAX_WALL_MINUTES:-30}"

  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$RUNTIME_MAP" "$MAX_VIEW" "$MAX_TOTAL" "$MAX_WALL" "${PHASE_DIR}" <<'PY'
import json, sys, time
from pathlib import Path
from datetime import datetime, timezone

rm_path = Path(sys.argv[1])
max_view = int(sys.argv[2])
max_total = int(sys.argv[3])
max_wall_min = int(sys.argv[4])
phase_dir = Path(sys.argv[5])

rm = json.loads(rm_path.read_text(encoding="utf-8"))
views = rm.get("views", {}) or {}
seqs = rm.get("goal_sequences", {}) or {}

per_view_actions = {}
total_actions = 0

# Count goal_sequences steps grouped by start_view
for gid, seq in seqs.items():
    start = seq.get("start_view") or "<unknown>"
    n = len(seq.get("steps", []) or [])
    per_view_actions[start] = per_view_actions.get(start, 0) + n
    total_actions += n

# Add free_exploration actions if tracked per view
for v_url, v in views.items():
    fe = (v.get("free_exploration") or {}).get("actions_count", 0) or 0
    per_view_actions[v_url] = per_view_actions.get(v_url, 0) + fe
    total_actions += fe

# Wall time — use session-start marker mtime as proxy for discovery start
marker = phase_dir / ".step-markers" / "00_session_lifecycle.done"
wall_min = None
if marker.exists():
    wall_min = (time.time() - marker.stat().st_mtime) / 60.0

# Evaluate
warnings = []
for v, n in per_view_actions.items():
    if n > max_view:
        warnings.append({"type": "view_overflow", "view": v, "count": n, "limit": max_view})
if total_actions > max_total:
    warnings.append({"type": "total_overflow", "count": total_actions, "limit": max_total})
if wall_min is not None and wall_min > max_wall_min:
    warnings.append({"type": "wall_overflow", "minutes": round(wall_min, 1), "limit": max_wall_min})

# Report
if warnings:
    print(f"⚠ R8 exploration limits exceeded ({len(warnings)} signal):")
    for w in warnings:
        if w["type"] == "view_overflow":
            print(f"   - view '{w['view']}' → {w['count']} actions vượt limit {w['limit']}")
        elif w["type"] == "total_overflow":
            print(f"   - total → {w['count']} actions vượt limit {w['limit']}")
        elif w["type"] == "wall_overflow":
            print(f"   - wall time (thời gian) → {w['minutes']} min vượt limit {w['limit']}")
    print("")
    print("Khuyến nghị (recommendation):")
    print("  - Review RUNTIME-MAP.json: có action lặp/vô ích không")
    print("  - Giảm views scanned hoặc tắt --full-scan (sidebar suppression giúp giảm action)")
    print("  - Nếu phase lớn thật, tăng config.review.max_actions_total")
else:
    wall_txt = f", {wall_min:.1f} min" if wall_min else ""
    print(f"✓ Exploration within limits: {total_actions} actions, {len(per_view_actions)} views{wall_txt}")

# Log to PIPELINE-STATE.json regardless
state_path = phase_dir / "PIPELINE-STATE.json"
state = {}
if state_path.exists():
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        state = {}
state.setdefault("metrics", {})["review_exploration"] = {
    "total_actions": total_actions,
    "views_scanned": len(per_view_actions),
    "wall_minutes": round(wall_min, 1) if wall_min is not None else None,
    "thresholds": {"per_view": max_view, "total": max_total, "wall_min": max_wall_min},
    "warnings": warnings,
    "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
PY

  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_exploration_limits" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_exploration_limits.done"

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2_exploration_limits 2>/dev/null || true
fi
```

**Hành vi downstream:** nếu có warnings, step `crossai_review` cuối pipeline sẽ include "exploration noisy" flag vào context để CrossAI xem xét kỹ goals liên quan views overflow.
</step>

<step name="phase2_7_url_state_sync" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.7: URL state sync declaration check (Phase J)

→ `narrate_phase "Phase 2.7 — URL state sync" "Kiểm tra interactive_controls trong TEST-GOALS"`

**Purpose:** validate every list/table/grid view goal in TEST-GOALS.md
declares `interactive_controls` block (filter/sort/pagination/search +
URL sync assertion). This is the static-side complement to runtime
browser probing — declaration must exist before runtime can verify.

**CRUD surface precheck (v2.12):** before URL-state checks, validate
`${PHASE_DIR}/CRUD-SURFACES.md`. Review compares runtime observations against
the resource/platform contract first, then uses `interactive_controls` as the
web-list extension pack. Missing CRUD contract means the reviewer has no
authoritative list of expected headings, filters, columns, states, row actions,
delete confirmations, or security/abuse expectations.

```bash
CRUD_FLAGS=""
[[ "${ARGUMENTS:-}" =~ --allow-no-crud-surface ]] && CRUD_FLAGS="--allow-missing"
CRUD_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-crud-surface-contract.py"
if [ -x "$CRUD_VAL" ]; then
  mkdir -p "${PHASE_DIR}/.tmp"
  "${PYTHON_BIN:-python3}" "$CRUD_VAL" --phase "${PHASE_NUMBER}" \
    --config "${REPO_ROOT}/.claude/vg.config.md" ${CRUD_FLAGS} \
    > "${PHASE_DIR}/.tmp/crud-surface-review.json" 2>&1
  CRUD_RC=$?
  if [ "$CRUD_RC" != "0" ]; then
    echo "⛔ CRUD surface contract missing/incomplete — see ${PHASE_DIR}/.tmp/crud-surface-review.json"
    echo "   Fix blueprint artifact CRUD-SURFACES.md or rerun /vg:blueprint."
    exit 2
  fi
fi
```

**Why:** modern dashboard UX baseline (executor R7) requires list view
state synced to URL search params. Without declaration, AI executors
build local-state-only filters and ship apps that lose state on refresh.
This validator catches the gap at /vg:review time, before user sees it.

**Severity:** config-driven via `vg.config.md → ui_state_conventions.severity_phase_cutover`
(default 14). Phase number < cutover → WARN (grandfather). Phase ≥ cutover
→ BLOCK (mandatory). Override with `--allow-no-url-sync` to log soft OD
debt entry.

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-url-state-sync.py \
  --phase "${PHASE_NUMBER}" \
  --enforce-required-lenses \
  > "${PHASE_DIR}/.tmp/url-state-sync.json" 2>&1
URL_SYNC_RC=$?

if [ "${URL_SYNC_RC}" != "0" ]; then
  if [[ "${RUN_ARGS:-}" == *"--allow-no-url-sync"* ]]; then
    "${PYTHON_BIN}" .claude/scripts/vg-orchestrator override \
      --flag skip-url-state-sync \
      --reason "URL state sync waived for ${PHASE_NUMBER} via --allow-no-url-sync (soft debt logged)"
    echo "⚠ URL state sync gate waived via --allow-no-url-sync"
  else
    echo "⛔ URL state sync declarations missing — see ${PHASE_DIR}/.tmp/url-state-sync.json"
    cat "${PHASE_DIR}/.tmp/url-state-sync.json"
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.url_state_sync" \
        --phase-dir "$PHASE_DIR" \
        --input "${PHASE_DIR}/.tmp/url-state-sync.json" \
        --out-md "${PHASE_DIR}/.tmp/url-state-sync-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/url-state-sync-diagnostic.md" 2>/dev/null || true
    fi
    echo ""
    echo "Fix options:"
    echo "  1. Add interactive_controls blocks to TEST-GOALS.md per goal."
    echo "     Schema: .claude/commands/vg/_shared/templates/TEST-GOAL-enriched-template.md (Phase J section)."
    echo "  2. If state is genuinely local-only, declare url_sync: false + url_sync_waive_reason."
    echo "  3. Override (last resort): re-run with --allow-no-url-sync (logs soft OD debt)."
    exit 2
  fi
fi
```

**Future runtime probe (deferred to v2.9):** once RUNTIME-MAP.json is
populated by phase 2 browser discovery, a follow-up validator can click
each declared control via MCP Playwright + snapshot URL pre/post +
assert reload-survives. Static declaration check is the foundation that
makes runtime probe meaningful.

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_7_url_state_sync" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_7_url_state_sync.done"`
</step>

