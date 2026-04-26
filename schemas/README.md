# VG Artifact Schemas

JSON Schemas (draft-07) that lock the structural shape of the 6 core VG
artifacts produced per phase. Spec source: `.vg/workflow-hardening-v2.7/SPEC-E.md`.

## Catalogue

| Schema | Validates | Producer step |
|--------|-----------|---------------|
| `specs.v1.json` | `${PHASE_DIR}/SPECS.md` frontmatter | `/vg:specs` `write_specs` |
| `context.v1.json` | `${PHASE_DIR}/CONTEXT.md` frontmatter | `/vg:scope` `2_artifact_generation` |
| `plan.v1.json` | `${PHASE_DIR}/PLAN.md` frontmatter | `/vg:blueprint` `2a_plan` |
| `test-goals.v1.json` | `${PHASE_DIR}/TEST-GOALS.md` frontmatter | `/vg:blueprint` `2b5_test_goals` |
| `summary.v1.json` | `${PHASE_DIR}/SUMMARY.md` frontmatter | `/vg:build` `9_post_execution` |
| `uat.v1.json` | `${PHASE_DIR}/UAT.md` frontmatter (legacy `${phase}-UAT.md` also accepted) | `/vg:accept` `6_write_uat_md` |
| `interactive-controls.v1.json` | sub-schema referenced from `test-goals.v1.json` for the `interactive_controls` block | n/a |

## Strict frontmatter, lenient body

Each schema uses `additionalProperties: false` on the YAML frontmatter object.
Body section requirements (required H2 / H3 regex, decision-ID monotonicity,
goal-count consistency) live in the validator code at
`.claude/scripts/validators/verify-artifact-schema.py`, NOT in the JSON Schema
files. Authors stay free to add subsections, reorder paragraphs, or write extra
prose between required H2 anchors.

## Versioning policy

- Each schema's `$id` ends in `/v1`. Example:
  `https://vgflow.dev/schemas/specs.v1.json`.
- Future shape bumps land at a new file `{name}.v2.json` with a fresh `$id`.
- Validators reference a specific version — they never auto-upgrade.
- The validator is read-only — never mutates artifacts. Output is a list of
  JSON Pointers + human messages on stdout (PASS/WARN/BLOCK verdict).
- Grandfather support: env `VG_SCHEMA_GRANDFATHER_BEFORE=14` skips validation
  for any phase whose major number is below the cutoff. Useful when migrating
  legacy phases that pre-date schema enforcement.

## How to bump a schema

1. Copy `{name}.v1.json` → `{name}.v2.json`.
2. Edit the `$id` to end in `/v2`.
3. Update `verify-artifact-schema.py` to reference the new version under a
   feature flag or phase cutover (`VG_SCHEMA_VERSION` env or config field).
4. Add tests to `test_artifact_schema.py` covering the new shape.
5. Keep `v1.json` in place for grandfather phases until cleanup.

## Allowed JSON Schema keywords

The validator implements a hand-rolled minimal walker — only these keywords
are honoured. Other keywords are silently ignored.

- `type` — one of `object | array | string | integer | number | boolean | null`
- `required` — array of property names that must be present
- `enum` — array of allowed values (string compare)
- `pattern` — Python `re` regex over string values
- `minimum` / `maximum` — numeric bounds
- `minLength` / `maxLength` — string length bounds
- `minItems` / `maxItems` — array length bounds
- `items` — sub-schema applied to each array element
- `properties` — per-property sub-schemas
- `additionalProperties` — `true` (default) or `false` to forbid extras

`oneOf`, `allOf`, `anyOf`, `$ref`, `if/then/else` are NOT supported. Keep
schemas flat.
