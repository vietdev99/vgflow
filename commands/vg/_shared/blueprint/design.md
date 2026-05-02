# blueprint design (STEP 2)

UI/design-related steps: 2_fidelity_profile_lock, 2b6c_view_decomposition,
2b6_ui_spec, 2b6b_ui_map. Profile-aware (web-fullstack, web-frontend-only).

<HARD-GATE>
For backend-only / cli-tool / library profiles, this STEP is SKIPPED via
profile branch. For web profiles, you MUST execute all 4 sub-steps.
</HARD-GATE>

## STEP 2.1 — fidelity profile lock (2_fidelity_profile_lock)

Lock the design fidelity profile (pixel-perfect | semantic | structural):

```bash
python3 .claude/scripts/vg-fidelity-lock.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2_fidelity_profile_lock.done"
vg-orchestrator mark-step blueprint 2_fidelity_profile_lock
```

## STEP 2.2 — view decomposition (2b6c_view_decomposition)

Decompose the phase into UI views (one per route/screen):

```bash
python3 .claude/scripts/vg-view-decompose.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2b6c_view_decomposition.done"
vg-orchestrator mark-step blueprint 2b6c_view_decomposition
```

## STEP 2.3 — UI spec (2b6_ui_spec)

Write per-view UI spec (component tree + interactions):

```bash
# AI generates UI-SPEC.md per template
[ -f "${PHASE_DIR}/UI-SPEC.md" ] || { echo "UI-SPEC.md missing"; exit 1; }
touch "${PHASE_DIR}/.step-markers/2b6_ui_spec.done"
vg-orchestrator mark-step blueprint 2b6_ui_spec
```

## STEP 2.4 — UI map (2b6b_ui_map)

Build mapping: view → component → state → API endpoint:

```bash
python3 .claude/scripts/vg-ui-map.py --phase ${PHASE_NUMBER}
[ -f "${PHASE_DIR}/UI-MAP.md" ] || { echo "UI-MAP.md missing"; exit 1; }
touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"
vg-orchestrator mark-step blueprint 2b6b_ui_map
```

After all 4 markers touched, return to entry SKILL.md and proceed to STEP 3.
