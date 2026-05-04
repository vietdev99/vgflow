# Pass 2 delegation prompt (Task 38)

Use this template when spawning `vg-blueprint-fe-contracts`. Substitute
`${PHASE_DIR}` with the phase directory path before spawn.

```
You are vg-blueprint-fe-contracts (Pass 2). Generate BLOCK 5 FE consumer
contract for each endpoint in API-CONTRACTS.

Read these inputs:
- @${PHASE_DIR}/API-CONTRACTS/index.md (TOC of endpoints)
- @${PHASE_DIR}/API-CONTRACTS/<each-slug>.md (BLOCKs 1-4 per endpoint)
- @${PHASE_DIR}/UI-MAP.md
- @${PHASE_DIR}/VIEW-COMPONENTS.md
- @${PHASE_DIR}/PLAN.md (for component-name hints)

For EACH endpoint, emit BLOCK 5 with all 16 required fields. See
agents/vg-blueprint-fe-contracts/SKILL.md for field schema + per-method matrix.

Return JSON to stdout (no other output):
{
  "endpoints": [
    { "slug": "post-api-sites", "block5_body": "export const ... as const;" },
    { "slug": "get-api-sites", "block5_body": "export const ... as const;" }
  ],
  "notes": [...]   // optional: flag missing UI-MAP entries, ambiguous role mappings, etc.
}

The orchestrator merges each block5_body into the matching contract file.
```

## Anti-drift checklist (validator-aligned)

Each `block5_body` MUST:
- Open with `export const <PascalEndpointName>FEContract = {`
- Close with `} as const;`
- Contain exactly 16 keys (validator regex matches each `<field>:` token)
- Set per-method matrix fields non-null per Task 38 spec
