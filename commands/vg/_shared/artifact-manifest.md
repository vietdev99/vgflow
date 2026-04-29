---
name: vg:_shared:artifact-manifest
description: Artifact Manifest (Shared Reference) — SHA256 manifest per phase artifacts, atomic group commit, validation gate on read. Detects partial-write corruption from crashes, race conditions, disk-full.
---

# Artifact Manifest — Shared Helper

> **⚠ Runtime note (v1.9.0 T3):** Runnable bash code is at [`_shared/lib/artifact-manifest.sh`](lib/artifact-manifest.sh). Commands MUST `source` the `.sh` file — this `.md` file is documentation only (YAML frontmatter + markdown headers + fenced code blocks cannot be sourced by bash). The bash snippets below are kept in sync with `.sh` for readability.

## Problem solved (per claude reviewer M10)

Multi-file outputs (PLAN.md + API-CONTRACTS.md + TEST-GOALS.md together) không atomic group. Mid-write crash → file 1+2 written, file 3 missing OR partial. Reading commands silently consume inconsistent artifacts. Build wave produces code against incomplete contract. Bugs blamed on implementation, not corruption. Hours of forensic debugging.

## Solution

Each phase has `.artifact-manifest.json` listing every expected artifact với SHA256 + bytes + lines. Manifest written **LAST** after all artifacts complete. Reading commands MUST validate manifest first; mismatch → BLOCK with explicit error message.

## Manifest schema

```json
{
  "manifest_version": "1.8.0",
  "phase": "07.10.1",
  "generated_at": "2026-04-17T09:12:33Z",
  "generated_by": "vg:blueprint v1.8.0",
  "session_id": "abc123",
  "artifacts": [
    {
      "path": "PLAN.md",
      "sha256": "abc123...",
      "bytes": 12345,
      "lines": 234,
      "category": "plan"
    },
    {
      "path": "API-CONTRACTS.md",
      "sha256": "def456...",
      "bytes": 4567,
      "lines": 89,
      "category": "contract"
    }
  ],
  "manifest_sha256": "ghi789..."
}
```

`manifest_sha256` = SHA256 of manifest excluding `manifest_sha256` field (self-describing integrity).

## API

```bash
# Write manifest after artifact group complete
# Usage: artifact_manifest_write PHASE_DIR COMMAND ARTIFACT_PATH1 [ARTIFACT_PATH2 ...]
# Returns: 0 on success, 1 on failure
artifact_manifest_write() {
  local phase_dir="$1"; shift
  local command="$1"; shift
  local manifest_path="${phase_dir}/.artifact-manifest.json"
  local tmp_manifest="${manifest_path}.tmp"

  ${PYTHON_BIN:-python3} - "$phase_dir" "$command" "$tmp_manifest" "${TELEMETRY_SESSION_ID:-unknown}" "$@" <<'PY'
import json, sys, hashlib, datetime
from pathlib import Path

phase_dir = Path(sys.argv[1])
command = sys.argv[2]
tmp_manifest = sys.argv[3]
session_id = sys.argv[4]
artifact_paths = sys.argv[5:]

artifacts = []
for rel in artifact_paths:
    abs_path = phase_dir / rel if not rel.startswith('/') else Path(rel)
    if not abs_path.exists():
        print(f"⛔ Artifact missing: {abs_path}", file=sys.stderr)
        sys.exit(1)
    data = abs_path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    try:
        lines = data.decode('utf-8', errors='ignore').count('\n') + (0 if data.endswith(b'\n') else 1)
    except Exception:
        lines = 0
    # Categorize by extension
    ext = abs_path.suffix.lower()
    cat_map = {'.md': 'doc', '.json': 'data', '.yaml': 'config', '.yml': 'config', '.png': 'image'}
    artifacts.append({
        "path": rel if not rel.startswith('/') else abs_path.name,
        "sha256": sha,
        "bytes": len(data),
        "lines": lines,
        "category": cat_map.get(ext, 'unknown')
    })

manifest = {
    "manifest_version": "1.8.0",
    "phase": phase_dir.name.split("-", 1)[0] if "-" in phase_dir.name else phase_dir.name,
    "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "generated_by": command,
    "session_id": session_id,
    "artifacts": artifacts
}
# Self-describing integrity: hash of manifest WITHOUT manifest_sha256 field
canonical = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode('utf-8')
manifest["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()

Path(tmp_manifest).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
print(f"✓ Manifest staged: {len(artifacts)} artifacts")
PY

  if [ $? -ne 0 ]; then
    rm -f "$tmp_manifest" 2>/dev/null
    return 1
  fi

  # Atomic promote
  mv "$tmp_manifest" "$manifest_path"

  # Telemetry
  type emit_telemetry_v2 >/dev/null 2>&1 && {
    local artifact_count=$(echo "$@" | wc -w)
    emit_telemetry_v2 "artifact_written" "$(basename "$phase_dir" | grep -oE '^[0-9.]+')" \
      "manifest_write" "" "PASS" "{\"artifact_count\":${artifact_count}}"
  }
  return 0
}

# Validate manifest before reading artifacts
# Usage: artifact_manifest_validate PHASE_DIR
# Returns: 0 if valid, 1 if missing manifest, 2 if mismatch (corruption)
artifact_manifest_validate() {
  local phase_dir="$1"
  local manifest_path="${phase_dir}/.artifact-manifest.json"

  # Legacy phases (pre-v1.8.0) without manifest → WARN but proceed
  if [ ! -f "$manifest_path" ]; then
    echo "⚠ No artifact manifest in ${phase_dir} (legacy phase, pre-v1.8.0). Proceeding without integrity check."
    echo "   Manifest will be backfilled on next blueprint/review write."
    return 1
  fi

  ${PYTHON_BIN:-python3} - "$phase_dir" <<'PY'
import json, sys, hashlib
from pathlib import Path

phase_dir = Path(sys.argv[1])
manifest_path = phase_dir / ".artifact-manifest.json"
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))

# 1. Validate manifest self-integrity
expected_sha = manifest.pop("manifest_sha256", None)
canonical = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode('utf-8')
actual_sha = hashlib.sha256(canonical).hexdigest()
if expected_sha != actual_sha:
    print(f"⛔ MANIFEST CORRUPTION (manifest tự sai): manifest_sha256 mismatch")
    print(f"   Expected: {expected_sha}")
    print(f"   Actual:   {actual_sha}")
    sys.exit(2)

# 2. Validate each artifact
mismatches = []
missing = []
for art in manifest["artifacts"]:
    abs_path = phase_dir / art["path"]
    if not abs_path.exists():
        missing.append(art["path"])
        continue
    actual = hashlib.sha256(abs_path.read_bytes()).hexdigest()
    if actual != art["sha256"]:
        mismatches.append({
            "path": art["path"],
            "expected": art["sha256"][:12],
            "actual": actual[:12]
        })

if missing:
    print(f"⛔ ARTIFACT MISSING (file thiếu — possible corruption hoặc rm):")
    for p in missing: print(f"   • {p}")
    print(f"   Recommended: re-run command that produced these artifacts (vg:blueprint hoặc vg:review).")
    sys.exit(2)

if mismatches:
    print(f"⛔ ARTIFACT CORRUPTION (file đã sửa sau write):")
    for m in mismatches:
        print(f"   • {m['path']}: expected {m['expected']}... actual {m['actual']}...")
    print(f"   Possible cause: manual edit, partial write recovery, or git checkout mid-write.")
    print(f"   Recommended: revert artifact OR re-run command + commit fresh.")
    sys.exit(2)

print(f"✓ Manifest valid: {len(manifest['artifacts'])} artifacts integrity-checked")
sys.exit(0)
PY
  local rc=$?

  # Telemetry
  type emit_telemetry_v2 >/dev/null 2>&1 && {
    local outcome="PASS"
    [ $rc -eq 1 ] && outcome="WARN"
    [ $rc -eq 2 ] && outcome="FAIL"
    emit_telemetry_v2 "artifact_read_validated" "$(basename "$phase_dir" | grep -oE '^[0-9.]+')" \
      "manifest_validate" "" "$outcome" "{}"
  }
  return $rc
}

# Backfill manifest for legacy phases (called on first read of legacy phase)
# Usage: artifact_manifest_backfill PHASE_DIR COMMAND_NAME
artifact_manifest_backfill() {
  local phase_dir="$1"
  local command="${2:-vg:auto-backfill}"
  local manifest_path="${phase_dir}/.artifact-manifest.json"

  [ -f "$manifest_path" ] && return 0  # already exists

  # Auto-discover artifacts in phase dir (markdown + json files)
  local artifacts=()
  while IFS= read -r f; do
    artifacts+=("$(basename "$f")")
  done < <(find "$phase_dir" -maxdepth 1 -type f \( -name '*.md' -o -name '*.json' \) | sort)

  [ ${#artifacts[@]} -eq 0 ] && return 0

  artifact_manifest_write "$phase_dir" "$command" "${artifacts[@]}"
  echo "ℹ Backfilled manifest for legacy phase: ${#artifacts[@]} artifacts"
}
```

## Integration pattern

### Writing (blueprint/build/review/test)

After all artifacts in a group are written and committed:

```bash
# /vg:blueprint after writing PLAN + API-CONTRACTS + TEST-GOALS
artifact_manifest_write "$PHASE_DIR" "vg:blueprint v1.8.0" \
  "PLAN.md" "API-CONTRACTS.md" "TEST-GOALS.md"
# Manifest written; reading commands now have integrity reference
```

### Reading (any command consuming phase artifacts)

At top of command, before reading artifacts:

```bash
artifact_manifest_validate "$PHASE_DIR"
case $? in
  0) ;;  # valid, proceed
  1)
    # Legacy phase — backfill manifest, then proceed
    artifact_manifest_backfill "$PHASE_DIR" "$VG_CURRENT_COMMAND"
    ;;
  2)
    # Corruption detected — BLOCK
    echo "⛔ Cannot proceed with corrupted artifacts. Fix above issues first."
    exit 1
    ;;
esac
# Safe to read artifacts now
```

## Per-command integration (v1.8.0 rollout)

| Command | Write timing | Artifacts |
|---------|-------------|-----------|
| `/vg:project` | After Round 7 atomic write | `PROJECT.md`, `FOUNDATION.md`, `vg.config.md` (project-level manifest at `${PLANNING_DIR}/.artifact-manifest.json`) |
| `/vg:roadmap` | After ROADMAP.md write | `ROADMAP.md` (project-level) |
| `/vg:specs` | After write | `SPECS.md` |
| `/vg:scope` | After Round 5 write | `CONTEXT.md`, `DISCUSSION-LOG.md` |
| `/vg:blueprint` | After all 3 written | `PLAN.md`, `API-CONTRACTS.md`, `TEST-GOALS.md` |
| `/vg:build` | After SUMMARY.md write per wave | `SUMMARY.md`, wave-specific files |
| `/vg:review` | After RUNTIME-MAP write | `RUNTIME-MAP.json`, `RUNTIME-MAP.md`, `GOAL-COVERAGE-MATRIX.md`, `UNREACHABLE-TRIAGE.md` (if exists) |
| `/vg:test` | After SANDBOX-TEST write | `SANDBOX-TEST.md` |
| `/vg:accept` | After UAT.md write | `UAT.md` |

| Command | Read validation | Artifacts validated before consuming |
|---------|-----------------|--------------------------------------|
| `/vg:scope` | Read SPECS.md | manifest validates SPECS exists + intact |
| `/vg:blueprint` | Read SPECS + CONTEXT | both manifests validated |
| `/vg:build` | Read PLAN + API-CONTRACTS + TEST-GOALS | blueprint manifest validated |
| `/vg:review` | Read SUMMARY + API-CONTRACTS | build + blueprint manifests |
| `/vg:test` | Read RUNTIME-MAP + GOAL-COVERAGE | review manifest |
| `/vg:accept` | Read everything | all upstream manifests validated as final gate |

## Edge cases

**Manual edit after manifest write:** User edits PLAN.md by hand → SHA256 mismatch → next read BLOCKS. Recovery: re-run `/vg:blueprint` (regenerates manifest with new content) OR `git checkout PLAN.md` (revert to manifest version).

**Partial git stash/pop:** Manifest references SHA of pre-stash content. After pop, content matches → no issue. If pop conflicts left half-merged file → BLOCK at next read.

**Multi-session edits:** Manifest includes `session_id`. If session A wrote manifest, session B edits artifact, session B re-runs command without re-writing manifest → BLOCK on next session A continuation.

**File system race conditions:** Atomic write via `.tmp` + `mv` rename. On Windows: `mv` may fail if target locked → emit error + suggest retry.

## Success criteria

- Every phase has `.artifact-manifest.json` after first blueprint/review run
- Reading commands never consume corrupted/partial artifacts silently
- Mid-write crash detectable on next read (manifest missing OR mismatch)
- Manual edits flagged immediately (SHA256 mismatch)
- Legacy phases (pre-v1.8.0) auto-backfilled with WARN, don't block
- Telemetry tracks: artifact_written events, artifact_read_validated events with PASS/WARN/FAIL outcome
