---
name: vg:audit-scaffold
description: Audit commands/ for scaffold/drift anti-patterns (Batch 24)
allowed-tools:
  - Bash
  - Read
---

# /vg:audit-scaffold

Runs `scripts/audit/scaffold-detector.py` against `commands/vg/` to find
scaffold patterns (Agent-comment-only, failure-swallow, tool-in-bash,
unconditional-marker, glob-bypass).

## Usage

```bash
DET="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/audit/scaffold-detector.py"
[ -f "$DET" ] || DET="${REPO_ROOT:-.}/scripts/audit/scaffold-detector.py"
"${PYTHON_BIN:-python3}" "$DET" --scan-dir "${REPO_ROOT:-.}/commands/vg" --json
```

Default: advisory mode (exit 0 always). Pass `--threshold 0` for strict mode
(BLOCK on any finding).

## Patterns detected (first ship)

| Pattern | Name | Severity |
|---------|------|----------|
| A | agent_comment_only | high |
| C | failure_swallow | high |
| F | tool_directive_in_bash | high |
| G | unconditional_marker | medium |
| H | glob_bypass | low |

Patterns B (marker_no_evidence), D (orphan_must_write), E (agent_read_only_file_expect)
require cross-file analysis — deferred to future enhancement.

## CI gate

In `.github/workflows/release.yml` the detector runs pre-tarball with
`--threshold 50` baseline. Tune via telemetry as patterns evolve.
