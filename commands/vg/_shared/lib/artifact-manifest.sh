# shellcheck shell=bash
# Artifact Manifest — bash function library
# Companion runtime for: .claude/commands/vg/_shared/artifact-manifest.md
# Docs (schemas, integration pattern, edge cases) live in the .md file.
# This .sh file is the ONLY sourceable entry point — markdown is NOT sourceable
# because it contains YAML frontmatter + markdown headers + fenced code blocks.
#
# Exposed functions:
#   - artifact_manifest_write PHASE_DIR COMMAND ARTIFACT_PATH [ARTIFACT_PATH...]
#   - artifact_manifest_validate PHASE_DIR        (returns 0=ok, 1=missing, 2=corrupt)
#   - artifact_manifest_backfill PHASE_DIR [COMMAND]

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
    "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
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
