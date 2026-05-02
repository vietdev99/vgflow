# blueprint preflight (STEP 1)

Light steps: 0_design_discovery, 0_amendment_preflight, 1_parse_args,
create_task_tracker, 2_verify_prerequisites.

<HARD-GATE>
You MUST execute steps in this order. Each step finishes with a marker
touch. Skipping = Stop hook block.
</HARD-GATE>

## STEP 1.1 — design discovery (0_design_discovery)

Run discovery script:

```bash
python3 .claude/scripts/vg-design-discovery.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/0_design_discovery.done"
vg-orchestrator mark-step blueprint 0_design_discovery
```

## STEP 1.2 — amendment preflight (0_amendment_preflight)

Check for pending amendments:

```bash
if [ -f "${PHASE_DIR}/AMENDMENTS.md" ]; then
  python3 .claude/scripts/vg-check-amendments.py --phase ${PHASE_NUMBER}
fi
touch "${PHASE_DIR}/.step-markers/0_amendment_preflight.done"
vg-orchestrator mark-step blueprint 0_amendment_preflight
```

## STEP 1.3 — parse args (1_parse_args)

Parse the slash-command args ($ARGUMENTS). Extract:
- PHASE_NUMBER (positional)
- Flags: --skip-research, --gaps, --reviews, --text, --crossai-only,
  --skip-crossai, --from=<substep>, --override-reason=<text>, --apply-amendments

```bash
touch "${PHASE_DIR}/.step-markers/1_parse_args.done"
vg-orchestrator mark-step blueprint 1_parse_args
```

## STEP 1.4 — create task tracker (create_task_tracker)

Run the tasklist emitter:

```bash
python3 .claude/scripts/emit-tasklist.py \
  --command vg:blueprint \
  --profile $PROFILE \
  --phase ${PHASE_NUMBER}
```

This writes `.vg/runs/<run_id>/tasklist-contract.json`. THEN:

**You MUST IMMEDIATELY call TodoWrite with one item per checklist group from the contract.**
Use the JSON template printed by emit-tasklist.py output. Do NOT continue without TodoWrite.

After TodoWrite, the PostToolUse hook auto-writes signed evidence to
`.vg/runs/<run_id>/.tasklist-projected.evidence.json`.

```bash
touch "${PHASE_DIR}/.step-markers/create_task_tracker.done"
vg-orchestrator mark-step blueprint create_task_tracker
```

## STEP 1.5 — verify prerequisites (2_verify_prerequisites)

Verify CONTEXT.md exists, INTERFACE-STANDARDS template available, etc:

```bash
[ -f "${PHASE_DIR}/CONTEXT.md" ] || { echo "CONTEXT.md missing — run /vg:scope first"; exit 1; }
[ -f .vg/templates/INTERFACE-STANDARDS-template.md ] || { echo "interface template missing"; exit 1; }
touch "${PHASE_DIR}/.step-markers/2_verify_prerequisites.done"
vg-orchestrator mark-step blueprint 2_verify_prerequisites
```

After ALL 5 step markers touched, return to entry SKILL.md and proceed to STEP 2.
