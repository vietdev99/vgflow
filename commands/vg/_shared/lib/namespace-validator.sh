# shellcheck shell=bash
# Namespace Validator — D-XX / F-XX / P{phase}.D-XX write-strict gate
# Companion doc: referenced inline from scope.md + project.md + vg-executor-rules.md
#
# Contract: read-tolerant, write-strict.
#   READ  — legacy bare D-XX still accepted (commit-msg WARN, migrate tool converts)
#   WRITE — new artifact emissions MUST use fully qualified form:
#             • FOUNDATION.md  → F-XX
#             • phase CONTEXT  → P{phase}.D-XX
#
# Exposed functions:
#   - validate_d_xx_namespace FILE_PATH SCOPE_KIND     (returns 0 = valid, 1 = violations)
#       SCOPE_KIND ∈ { "foundation" | "phase:<N>" }
#   - validate_d_xx_namespace_stdin SCOPE_KIND         (reads stdin)
#
# Usage examples:
#   validate_d_xx_namespace "${PHASE_DIR}/CONTEXT.md.staged" "phase:7.12" || exit 1
#   cat generated.md | validate_d_xx_namespace_stdin "foundation" || exit 1

# Internal — run the python analyzer against a file path, write violations to stderr,
# return 0 (clean) / 1 (violations) / 2 (bad args).
validate_d_xx_namespace() {
  local file_path="$1"
  local scope_kind="${2:-unknown}"

  if [ ! -f "$file_path" ]; then
    echo "⛔ validate_d_xx_namespace: file not found: ${file_path}" >&2
    return 2
  fi

  local expected_prefix expected_form phase_num
  case "$scope_kind" in
    foundation)
      expected_prefix="F-"
      expected_form="F-XX"
      ;;
    phase:*)
      phase_num="${scope_kind#phase:}"
      expected_prefix="P${phase_num}.D-"
      expected_form="P${phase_num}.D-XX"
      ;;
    *)
      echo "⛔ validate_d_xx_namespace: unknown scope_kind='${scope_kind}' (expected 'foundation' or 'phase:<N>')" >&2
      return 2
      ;;
  esac

  # Run analyzer — prints one violation per line to stdout, rc=1 if any.
  local violations
  violations=$(${PYTHON_BIN:-python3} - "$file_path" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")

# Strip fenced code blocks + blockquote lines (docs/examples tolerated).
lines = text.split("\n")
cleaned_lines = []
in_fence = False
for i, ln in enumerate(lines, 1):
    stripped = ln.lstrip()
    if stripped.startswith("```") or stripped.startswith("~~~"):
        in_fence = not in_fence
        cleaned_lines.append("")       # placeholder preserves line numbers
        continue
    if in_fence:
        cleaned_lines.append("")
        continue
    if stripped.startswith(">"):
        cleaned_lines.append("")       # blockquote = citation/example
        continue
    cleaned_lines.append(ln)

bare_re = re.compile(r'(?<![\w.])(D-\d+)(?!\w)')
hits = []
for i, ln in enumerate(cleaned_lines, 1):
    for m in bare_re.finditer(ln):
        # Skip inline-code spans `D-XX` (odd backtick count before match on same line)
        before = ln[:m.start()]
        if before.count("`") % 2 == 1:
            continue
        hits.append((i, m.group(1), ln.strip()[:120]))

for lineno, did, snippet in hits:
    print(f"{lineno}|{did}|{snippet}")
sys.exit(1 if hits else 0)
PY
)
  local rc=$?

  if [ $rc -eq 1 ] && [ -n "$violations" ]; then
    echo "" >&2
    echo "⛔ NAMESPACE WRITE-STRICT (vi phạm không gian tên) — bare D-XX detected in ${scope_kind} artifact: ${file_path}" >&2
    echo "   New artifact writes (v1.9.0+) MUST use fully-qualified namespace: ${expected_form}" >&2
    echo "   (legacy bare D-XX vẫn được đọc — commit-msg hook WARN; nhưng KHÔNG được ghi mới từ v1.9.0)" >&2
    echo "" >&2
    echo "   Violations:" >&2
    while IFS='|' read -r lineno did snippet; do
      [ -z "$lineno" ] && continue
      echo "     • line ${lineno}: found '${did}' — should be '${expected_prefix}${did#D-}'" >&2
      echo "         ctx: ${snippet}" >&2
    done <<< "$violations"
    echo "" >&2
    echo "   Fix options (sửa):" >&2
    echo "     (a) Rewrite occurrences to '${expected_form}' inline (khuyến nghị)." >&2
    echo "     (b) Wrap example text inside fenced \`\`\` code block (docs/migration samples tolerated)." >&2
    echo "     (c) Run '.claude/scripts/migrate-d-xx-namespace.py --apply' on existing legacy artifact before append." >&2
    return 1
  fi
  return 0
}

# Stdin convenience — writes stdin to temp file then delegates.
validate_d_xx_namespace_stdin() {
  local scope_kind="${1:-unknown}"
  local tmp
  tmp=$(mktemp -t vg-nsval.XXXXXX) || {
    echo "⛔ validate_d_xx_namespace_stdin: mktemp failed" >&2
    return 2
  }
  cat > "$tmp"
  validate_d_xx_namespace "$tmp" "$scope_kind"
  local rc=$?
  rm -f "$tmp"
  return $rc
}
