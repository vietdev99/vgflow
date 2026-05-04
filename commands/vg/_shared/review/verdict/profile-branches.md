# review verdict — profile-specific branches (web-frontend-only / web-backend-only / mobile-* / cli-tool / library)

This branch fires when `PHASE_PROFILE` is none of `{feature, web-fullstack}` and
`UI_GOAL_COUNT > 0`. The Phase 4 pipeline structure mirrors `web-fullstack.md`
but with profile-specific differences in surface routing, invariant validators,
and UNREACHABLE triage paths. The legacy unreachable_triage step (lines 7000-7022
of review.md backup) lives here as a fallback guard for legacy flows that bypass
inline triage at 4d (e.g., `--skip-discovery` + `--fix-only`).

vg-load convention: identical to web-fullstack.md — `vg-load --priority critical`
+ `--goal G-NN` for AI-context goal loads. Profile-specific helpers (mobile
deploy, CLI smoke tests) read flat artifacts via grep/JSON parse.

---

## STEP 7.C-PROFILE — branching by PHASE_PROFILE

```
case "$PHASE_PROFILE" in
  web-frontend-only)
    # Same pipeline as web-fullstack BUT skip API contract probe in 4c
    # (FE phase has no BE routes to validate). Mirror 4a-4f from web-fullstack.md
    # but with verify-interface-standards and verify-error-message-runtime gated
    # on FE-only contracts.
    ;;
  web-backend-only)
    # No browser RUNTIME-MAP (UI goals are zero by definition — but if non-zero
    # because TEST-GOALS misclassified, fall through to web-fullstack pipeline).
    # Skip verify-haiku-scan-completeness, verify-runtime-map-coverage,
    # verify-error-message-runtime. Run rest of 8 invariants.
    ;;
  mobile-ios|mobile-android|mobile-*)
    # Mobile uses UI scanning via mobile harness (not Playwright). RUNTIME-MAP
    # schema is identical, but goal_sequences come from mobile-discovery scanner
    # (phase2_mobile_discovery, line 4780 in backup). 4a-4f gates apply with
    # mobile-specific overrides:
    #   - verify-mobile-screenshot-coverage replaces verify-haiku-scan-completeness
    #   - phase2_5_mobile_visual_checks replaces phase2_5_visual_checks
    # See commands/vg/_shared/mobile-deploy.md for env-specific deploy hooks.
    ;;
  cli-tool|library)
    # No UI surface. Run 4a load goals + classify, surface probes only (no
    # browser, no RUNTIME-MAP), then 4c matrix-merger + reduced invariants
    # (same subset as pure-backend-fastpath.md). Goals classified surface=cli
    # → grep entry-point script + man page; surface=library → grep public API
    # signature in src/.
    ;;
  hotfix|bugfix|migration|docs)
    # Handled at preflight phase_profile_branch — those modes short-circuit
    # to phaseP_* steps (delta / regression / schema-verify / link-check) and
    # never enter Phase 4 classic pipeline. If we got here with one of these
    # profiles, REVIEW_MODE was overridden to full → fall through to
    # web-fullstack.md pipeline.
    ;;
esac
```

The actual implementation pulls from `web-fullstack.md` (4a-4f) with the
profile-specific overrides above. Differences:

| Profile | RUNTIME-MAP | Surface probes | Invariants subset | UNREACHABLE triage |
|---|---|---|---|---|
| web-frontend-only | UI only (no API endpoints) | api/data goals = INFRA_PENDING by default | skip verify-crud-runs-coverage | scope-tag verdict via FE-only frame |
| web-backend-only | empty stub | full surface probes | skip verify-haiku-scan-completeness + verify-runtime-map-coverage + verify-error-message-runtime | scope-tag verdict via BE-only frame |
| mobile-* | mobile screen graph | mobile-specific (deeplink, intent) | replace verify-haiku-scan-completeness with verify-mobile-screenshot-coverage | scope-tag verdict via mobile frame |
| cli-tool | empty stub | grep entrypoint script + man page | only verify-goal-security + verify-security-baseline | UNREACHABLE rare; mostly READY/INFRA_PENDING |
| library | empty stub | grep public API signatures | only verify-goal-security + verify-security-baseline | UNREACHABLE → "API not exported" |

---

## STEP 7.C-LEGACY — UNREACHABLE triage fallback (legacy guard)

<step name="unreachable_triage" mode="full">
## UNREACHABLE Triage — legacy guard (v1.14.0+)

**Từ v1.14.0, triage chạy INLINE trong Phase 4d (ngay trước cổng 100%).** Step này chỉ còn là **guard** cho trường hợp legacy flow đi vòng (ví dụ `--skip-discovery` + `--fix-only` nhảy qua 4d). Nếu `.unreachable-triage.json` đã tồn tại từ 4d → skip; nếu chưa → chạy fallback.

```bash
TRIAGE_JSON="${PHASE_DIR}/.unreachable-triage.json"
if [ -f "$TRIAGE_JSON" ]; then
  echo "ℹ Triage đã chạy inline ở Phase 4d — skip legacy guard."
else
  session_mark_step "4f-unreachable-triage-legacy"
  echo ""
  echo "🔍 Legacy path: UNREACHABLE triage fallback (4d bị bỏ qua)..."
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/unreachable-triage.sh" 2>/dev/null || true
  if type -t triage_unreachable_goals >/dev/null 2>&1; then
    triage_unreachable_goals "$PHASE_DIR" "$PHASE_NUMBER"
  else
    echo "⚠ unreachable-triage.sh missing — triage skipped" >&2
  fi
fi
```

**Lưu ý v1.14.0+:** Triage không còn là "report-only cho accept gate". Triage SINH action_required, review 4d ÁP DỤNG autonomous action (mark_deferred/mark_manual) và BLOCK gate cho action cần người duyệt (spawn_fix_agent, draft_amendment_ask, prompt_scope_tag). Xem spec section A.2.
</step>

---

## STEP 7.C-MOBILE — mobile-specific verdict overrides (mobile-* profiles only)

For `PHASE_PROFILE=mobile-*`, the following sub-steps from review.md
backup apply additionally:

- `phase2_mobile_discovery` (line 4780) — replaces phase2_browser_discovery for mobile (handled in discovery/overview.md as a sibling branch when SPAWN_MODE=sequential + profile=mobile-*)
- `phase2_5_mobile_visual_checks` (line 5245) — replaces phase2_5_visual_checks
- `verify-mobile-screenshot-coverage` invariant — runs in 4c instead of `verify-haiku-scan-completeness`

These deltas are mechanical drop-ins on top of the web-fullstack 4a-4f
flow; the gate decision (4f) is identical (PASS iff BLOCKED + UNREACHABLE == 0).

After Phase 4 completes for any of these profiles, control returns to
`overview.md` for the step-end marker write
(`mark_step phase4_goal_comparison`).
