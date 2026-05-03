# shellcheck shell=bash
# Bug Reporter — auto-detect workflow bugs + push to GitHub issues (v1.11.0 R5)
#
# Purpose: When AI orchestrator or helper detects a workflow bug (schema violation,
# helper error, user pushback, gate loop fatigue), auto-report to vietdev99/vgflow
# GitHub issues. Enables distributed bug collection from all VG users.
#
# Privacy: opt-out default (prompted during install). Redacts project paths/names
# before upload. Dedup via local cache + GitHub issue search.
#
# 2 event types, 1 pipeline:
#   - telemetry (info): install, update, command_invoked — batched weekly
#   - bug (error/critical): schema_violation, helper_error, user_pushback, gate_loop — per-incident
#
# Send strategy (3-tier fallback):
#   1. gh auth ok   → gh issue create (user's token)
#   2. gh not auth  → print prefilled URL for browser submit (anonymous)
#   3. silent skip  → queue locally, retry next session (auto_send_minor=true)
#
# Exposed functions:
#   bug_reporter_enabled
#   bug_reporter_consent_prompt                (first-run onboarding)
#   report_event TYPE SEVERITY DATA_JSON       (generic entry point)
#   report_bug SIGNATURE TYPE CONTEXT [SEVERITY]
#   report_telemetry TYPE DATA_JSON            (install/update/command_invoked)
#   bug_reporter_queue_show
#   bug_reporter_queue_flush
#   bug_reporter_dedup_check SIGNATURE         (returns 0 if new, 1 if sent)
#   bug_reporter_redact INPUT                  (strip paths/names)
#   bug_reporter_github_submit TITLE BODY LABELS  (try gh → URL fallback)

BUG_REPORTER_DEFAULT_REPO="vietdev99/vgflow"
BUG_REPORTER_DEFAULT_QUEUE=".claude/.bug-reports-queue.jsonl"
BUG_REPORTER_DEFAULT_SENT=".claude/.bug-reports-sent.jsonl"
BUG_REPORTER_DEFAULT_DISABLED=".claude/.bug-reports-disabled.txt"
BUG_REPORTER_DEFAULT_MAX_PER_SESSION=5

bug_reporter_enabled() {
  [ "${CONFIG_BUG_REPORTING_ENABLED:-true}" = "true" ] || return 1
  return 0
}

# Write a disabled bug_reporting block to vg.config.md (precondition unmet).
bug_reporter_write_config_disabled() {
  local config="$1"
  local reason="$2"
  if ! grep -qE "^bug_reporting:" "$config" 2>/dev/null; then
    cat >> "$config" <<EOF

# ─── Bug Reporting (auto-disabled) ─────────────────────────────────
# $reason
# To enable later: install gh + auth, then /vg:bug-report --enable
bug_reporting:
  enabled: false
  disabled_reason: "$reason"
  repo: "vietdev99/vgflow"
EOF
  fi
}

# Check if user has consented (first run). Write consent decision to config.
# HARD requirement: gh CLI installed + authenticated. If missing → auto-disable + recommend install.
bug_reporter_consent_prompt() {
  local config=".claude/vg.config.md"
  if [ -f "$config" ] && grep -qE "^bug_reporting:" "$config"; then
    return 0  # already configured
  fi

  # Hard precondition: gh CLI must be installed AND authenticated.
  # No URL fallback — silent fallbacks mask delivery failures (URL never opened = bug lost).
  if ! command -v gh >/dev/null 2>&1; then
    echo ""
    echo "ℹ Bug reporting requires GitHub CLI (gh) — not installed."
    echo "  Auto-disabling bug_reporting. To enable later:"
    echo "    1. Install: https://cli.github.com  (Mac: brew install gh, Win: winget install GitHub.cli)"
    echo "    2. Auth:    gh auth login"
    echo "    3. Run:     /vg:bug-report --enable"
    echo ""
    bug_reporter_write_config_disabled "$config" "gh CLI not installed at consent-time"
    return 0
  fi
  if ! gh auth status >/dev/null 2>&1; then
    echo ""
    echo "ℹ Bug reporting requires GitHub CLI auth — not logged in."
    echo "  Run: gh auth login   then: /vg:bug-report --enable"
    echo ""
    bug_reporter_write_config_disabled "$config" "gh auth not configured at consent-time"
    return 0
  fi

  echo ""
  echo "═══════════════════════════════════════════════════════════════"
  echo "  VG Bug Reporting — help improve the workflow"
  echo "═══════════════════════════════════════════════════════════════"
  echo ""
  echo "VG có thể tự động gửi bug reports + install telemetry tới GitHub issues"
  echo "(repo vietdev99/vgflow) để giúp cải thiện workflow cho tất cả users."
  echo ""
  echo "Sẽ gửi:"
  echo "  ✓ Schema violations, helper errors, user pushback (bug reports)"
  echo "  ✓ Install/update events, command usage counts (telemetry, aggregated)"
  echo ""
  echo "KHÔNG gửi:"
  echo "  ✗ Project code content, decision details, PII"
  echo "  ✗ User email, git author, file contents"
  echo "  ✗ API endpoints với specific paths (sẽ được redact thành /api/v1/{resource})"
  echo ""
  echo "Redact rules applied trước khi upload:"
  echo "  - /home/user/project-xyz/ → {project_path}/"
  echo "  - 'VollxSSP' → '<project-name>'"
  echo "  - phase names → phase-{id}"
  echo ""
  echo "Opt-out anytime: /vg:bug-report --disable-all"
  echo ""
  read -r -p "Enable bug reporting? [Y/n] (default: Y): " answer
  answer="${answer:-Y}"

  local enabled
  case "$answer" in
    Y|y|yes|Yes) enabled="true" ;;
    *) enabled="false" ;;
  esac

  # Write to config if not already present
  if ! grep -qE "^bug_reporting:" "$config" 2>/dev/null; then
    cat >> "$config" <<EOF

# ─── Bug Reporting (v1.11.0) ───────────────────────────────────────
# Auto-detect workflow bugs + send to vietdev99/vgflow GitHub issues.
# User consented: $(date -u +%Y-%m-%dT%H:%M:%SZ)
bug_reporting:
  enabled: ${enabled}
  repo: "vietdev99/vgflow"
  severity_threshold: "minor"      # minor | medium | high | critical
  auto_send_minor: true             # true = silent background, false = confirm each
  redact_project_paths: true
  redact_project_names: true
  auto_assign: "vietdev99"          # GitHub handle to assign issues
  default_labels: ["bug-auto", "needs-triage"]
  max_per_session: 5
  queue_path: ".claude/.bug-reports-queue.jsonl"
  sent_cache_path: ".claude/.bug-reports-sent.jsonl"
EOF
    echo ""
    if [ "$enabled" = "true" ]; then
      echo "✓ Bug reporting enabled. Send 'install_success' event..."
      report_telemetry "install_consent" "{\"version\":\"$(cat .claude/VGFLOW-VERSION 2>/dev/null || echo unknown)\"}"
    else
      echo "✓ Bug reporting disabled. Re-enable: /vg:bug-report --enable"
    fi
  fi
}

# Count events sent this session (rate limit)
bug_reporter_session_count() {
  local marker="${VG_TMP:-/tmp}/bug-reporter-session-$$.count"
  [ -f "$marker" ] && cat "$marker" || echo 0
}

bug_reporter_session_increment() {
  local marker="${VG_TMP:-/tmp}/bug-reporter-session-$$.count"
  local n
  n=$(bug_reporter_session_count)
  echo $((n + 1)) > "$marker"
}

# Check if signature was already sent (dedup)
# Returns 0 if already sent, 1 if new (inverted for shell convention)
bug_reporter_dedup_check() {
  local sig="$1"
  local cache="${CONFIG_BUG_REPORTING_SENT_CACHE:-$BUG_REPORTER_DEFAULT_SENT}"
  [ -f "$cache" ] || return 1

  if grep -qF "\"signature\":\"${sig}\"" "$cache" 2>/dev/null; then
    return 0  # already sent
  fi
  return 1
}

# Check if signature is user-disabled
bug_reporter_disabled_check() {
  local sig="$1"
  local disabled="${CONFIG_BUG_REPORTING_DISABLED:-$BUG_REPORTER_DEFAULT_DISABLED}"
  [ -f "$disabled" ] || return 1
  grep -qF "$sig" "$disabled" 2>/dev/null
}

# Redact sensitive info from input text before upload.
# Rules: absolute paths → {project_path}/, project name → <project-name>,
# phase dir specifics → phase-{id}, git user email → omitted.
#
# Issue #22: original implementation used `sed 's|\\|/|g'` which was
# malformed (bash double-quote ate one backslash → sed got `s|\|/|g` →
# matched `|` literal, not `\`). Bash native `${x//\\//}` also fails on
# MSYS because glob pattern matcher drops backslashes. Using Python
# subprocess for the whole redact path: cross-platform, robust, and the
# file already uses Python for project_name + signature hashing.
bug_reporter_redact() {
  local input="$1"
  local repo_root="${REPO_ROOT:-$(pwd)}"
  REPO_ROOT_FOR_REDACT="$repo_root" \
  ${PYTHON_BIN:-python3} -c '
import os, re, sys
text = sys.stdin.read()
repo_root = os.environ.get("REPO_ROOT_FOR_REDACT", "")

# Project name from config (best-effort)
project_name = ""
try:
    cfg = open(".claude/vg.config.md", encoding="utf-8").read()
    m = re.search(r"^project_name:\s*\"([^\"]+)\"", cfg, re.M)
    if m:
        project_name = m.group(1)
except Exception:
    pass

# 1. Redact repo_root in BOTH backslash and forward-slash forms.
if repo_root:
    text = text.replace(repo_root, "{project_path}")
    fwd = repo_root.replace("\\", "/")
    if fwd != repo_root:
        text = text.replace(fwd, "{project_path}")

# 2. Redact project name (case-sensitive substring).
if project_name:
    text = text.replace(project_name, "<project-name>")

# 3. Redact phase dir patterns (e.g. "07.12-conversion-tracking-pixel" → "phase-{id}").
text = re.sub(r"[0-9]+(?:\.[0-9]+)*-[a-z][a-z0-9-]*", "phase-{id}", text)

# 4. Redact git emails.
text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "<email>", text)

sys.stdout.write(text)
' <<< "$input"
}

# Queue event to local JSONL (append)
bug_reporter_queue_event() {
  local event_json="$1"
  local queue="${CONFIG_BUG_REPORTING_QUEUE:-$BUG_REPORTER_DEFAULT_QUEUE}"
  mkdir -p "$(dirname "$queue")" 2>/dev/null || true
  echo "$event_json" >> "$queue"
}

# Main entry point: generic event reporting
# Usage: report_event TYPE SEVERITY DATA_JSON
report_event() {
  local type="$1"      # install / update / bug / command_invoked / schema_violation / ...
  local severity="$2"  # info | minor | medium | high | critical
  local data="$3"      # JSON string

  if ! bug_reporter_enabled; then
    return 0
  fi

  # Rate limit per session
  local max="${CONFIG_BUG_REPORTING_MAX_PER_SESSION:-$BUG_REPORTER_DEFAULT_MAX_PER_SESSION}"
  local count
  count=$(bug_reporter_session_count)
  if [ "$count" -ge "$max" ]; then
    echo "⚠ Bug reporter rate limit: ${count}/${max} per session. Skipping." >&2
    return 0
  fi

  # Compute signature (sha256 first 8 chars of type+redacted data)
  local redacted
  redacted=$(bug_reporter_redact "$data")
  local sig
  sig=$(echo -n "${type}|${redacted}" | ${PYTHON_BIN:-python3} -c "
import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:8])
" 2>/dev/null)

  # Dedup check
  if bug_reporter_dedup_check "$sig"; then
    return 0
  fi

  # Disabled check
  if bug_reporter_disabled_check "$sig"; then
    return 0
  fi

  # Build event JSON. Issue #34/35/36 (2026-04-29): pass values via env
  # vars instead of substituting into Python source. The earlier triple-
  # quote substitution `'''${redacted}'''` died with SyntaxError whenever
  # redacted JSON contained a quote/triple-quote/newline; `2>/dev/null`
  # then silently dropped the event → GitHub issues with empty context.
  local version
  version=$(cat .claude/VGFLOW-VERSION 2>/dev/null || echo "unknown")
  local event
  event=$(BR_SIG="$sig" BR_TYPE="$type" BR_SEV="$severity" \
          BR_VER="$version" BR_DATA="$redacted" \
          ${PYTHON_BIN:-python3} -c "
import json, os, sys, datetime
data_raw = os.environ.get('BR_DATA', '')
data_val = json.loads(data_raw) if data_raw.startswith('{') else data_raw
print(json.dumps({
  'signature': os.environ.get('BR_SIG', ''),
  'type': os.environ.get('BR_TYPE', ''),
  'severity': os.environ.get('BR_SEV', ''),
  'version': os.environ.get('BR_VER', ''),
  'os': sys.platform,
  'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'data': data_val,
}))
" 2>/dev/null)

  [ -z "$event" ] && return 0

  # Queue locally first (always)
  bug_reporter_queue_event "$event"
  bug_reporter_session_increment

  # Decide send mode
  local severity_threshold="${CONFIG_BUG_REPORTING_SEVERITY_THRESHOLD:-minor}"
  local auto_minor="${CONFIG_BUG_REPORTING_AUTO_SEND_MINOR:-true}"

  # Only send immediately if severity >= threshold
  if ! _severity_gte "$severity" "$severity_threshold"; then
    return 0  # queued only, sent later via --flush
  fi

  # Immediate send
  if [ "$severity" = "critical" ] || [ "$severity" = "high" ]; then
    bug_reporter_github_submit_from_event "$event"
  elif [ "$auto_minor" = "true" ]; then
    bug_reporter_github_submit_from_event "$event"
  else
    echo "⚠ Bug detected (severity: ${severity}, sig: ${sig})" >&2
    echo "  Run /vg:bug-report --flush to send, or --disable=${sig} to suppress" >&2
  fi
}

# Severity comparison helper
_severity_gte() {
  local actual="$1" threshold="$2"
  local order="info minor medium high critical"
  local actual_idx threshold_idx i=0
  for sev in $order; do
    [ "$sev" = "$actual" ] && actual_idx=$i
    [ "$sev" = "$threshold" ] && threshold_idx=$i
    i=$((i + 1))
  done
  [ -z "$actual_idx" ] && actual_idx=0
  [ -z "$threshold_idx" ] && threshold_idx=0
  [ "$actual_idx" -ge "$threshold_idx" ]
}

# Convenience: report_bug SIGNATURE_HINT TYPE CONTEXT [SEVERITY]
#
# Args (POSITIONAL — order matters, easy to swap by mistake):
#   $1 SIGNATURE_HINT  — short kebab-case identifier of the bug class
#                        e.g. "config-paths-missing-parent" / "install-missing-lib-sh-v1.11.0"
#                        Used as data.signature_hint; auto-hashed to short ID for dedup.
#                        DO NOT pass a generic type here ("schema_violation") — that's $2.
#   $2 TYPE            — bug taxonomy enum, one of:
#                        schema_violation | helper_error | user_pushback |
#                        ai_inconsistency | gate_loop | self_discovery | self_found
#                        DO NOT pass severity here ("high") — that's $4.
#   $3 CONTEXT         — free-form prose, the WHAT-and-WHY of the bug. 1-3 sentences.
#                        Will be json-encoded into data.context. Avoid unescaped quotes.
#   $4 SEVERITY        — optional enum, default "medium":
#                        info | minor | medium | high | critical
#                        Anything else (long string, etc.) → _severity_gte fails →
#                        bug silently queued, NOT sent. See issue vietdev99/vgflow#7.
#
# Example (CORRECT):
#   report_bug "config-paths-missing-parent" "schema_violation" \
#              "vg.config.md missing 'paths:' parent key after sed-replace" \
#              "high"
#
# Example (WRONG — will silently fail to send):
#   report_bug "schema_violation" "high" "<context>" "<severity-as-context>"
#   #          ^^^ this is type     ^^^ this is severity (now in $2!)
#
report_bug() {
  local sig="$1" type="$2" context="$3" severity="${4:-medium}"

  # Argument-shape guard (catch swap mistakes early — issue #7)
  case "$severity" in
    info|minor|medium|high|critical) ;;
    *)
      echo "⚠ report_bug: severity='${severity}' invalid (expected: info|minor|medium|high|critical)" >&2
      echo "  Likely arg-order swap. Function signature: report_bug SIG_HINT TYPE CONTEXT [SEVERITY]" >&2
      echo "  Defaulting severity=medium for this call. See issue vietdev99/vgflow#7." >&2
      severity="medium"
      ;;
  esac
  case "$type" in
    schema_violation|helper_error|user_pushback|ai_inconsistency|gate_loop|self_discovery|self_found) ;;
    *)
      echo "⚠ report_bug: type='${type}' not in standard taxonomy. Continuing but consider standard enum." >&2
      ;;
  esac

  # Issue #34/35/36 (2026-04-29): pass sig + context via env vars rather
  # than substituting them into the Python source. Earlier code used
  # `'''${context}'''` triple-quote substitution, which exploded into a
  # SyntaxError when context contained a quote, single-quote run, or
  # `$`/backtick — `2>/dev/null` swallowed the error so data became
  # empty. GitHub issue bodies came through with `Context: \`\`\`json\n\n\`\`\``.
  # Env-var passing is fully byte-safe: Python reads from os.environ.
  local data
  data=$(BR_SIG="$sig" BR_CTX="$context" ${PYTHON_BIN:-python3} -c "
import json, os
print(json.dumps({
    'signature_hint': os.environ.get('BR_SIG', ''),
    'context': os.environ.get('BR_CTX', ''),
}))
" 2>/dev/null)
  if [ -z "$data" ]; then
    # Fallback: never let report_bug submit with empty data — the issue
    # body becomes useless. Build a minimal sentinel JSON manually.
    data="{\"signature_hint\":\"${sig}\",\"context\":\"(context-encode-failed)\"}"
  fi
  report_event "$type" "$severity" "$data"
}

# Convenience: report_telemetry TYPE DATA_JSON (severity=info)
report_telemetry() {
  local type="$1" data="${2:-{}}"
  report_event "$type" "info" "$data"
}

# Submit single event as GitHub issue (3-tier fallback)
bug_reporter_github_submit_from_event() {
  local event="$1"
  local repo="${CONFIG_BUG_REPORTING_REPO:-$BUG_REPORTER_DEFAULT_REPO}"
  local assignee="${CONFIG_BUG_REPORTING_AUTO_ASSIGN:-vietdev99}"
  local labels="${CONFIG_BUG_REPORTING_DEFAULT_LABELS:-bug-auto,needs-triage}"

  local sig type severity version
  sig=$(echo "$event" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('signature',''))" 2>/dev/null)
  type=$(echo "$event" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('type',''))" 2>/dev/null)
  severity=$(echo "$event" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('severity',''))" 2>/dev/null)
  version=$(echo "$event" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('version',''))" 2>/dev/null)

  local title="[${severity}] ${type} — sig ${sig} (vg ${version})"
  local body
  body=$(BR_EVENT="$event" "${PYTHON_BIN:-python3}" -c '
import json, os
ev = json.loads(os.environ.get("BR_EVENT", "{}"))
print(f"""**Auto-reported via vg bug-reporter** (v{ev.get("version", "?")})

## Signature
`{ev.get("signature", "?")}` — if matches existing issue, please add as comment.

## Type
{ev.get("type", "?")}

## Severity
{ev.get("severity", "?")}

## Environment
- VG version: {ev.get("version", "?")}
- OS: {ev.get("os", "?")}
- Detected: {ev.get("ts", "?")}

## Context
```json
{json.dumps(ev.get("data", "{}"), indent=2) if isinstance(ev.get("data"), dict) else ev.get("data", "")}
```

---
🤖 Auto-submitted via vg bug-reporter. If this duplicates an existing issue, please link + close. Suppress future reports of this signature on sender side: `/vg:bug-report --disable={ev.get("signature", "")}`
""")
' 2>/dev/null)

  # Tier 1: gh CLI
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    # Check if issue with same signature exists
    local existing
    existing=$(gh issue list --repo "$repo" --search "sig ${sig}" --json number,title --jq '.[0].number' 2>/dev/null)
    if [ -n "$existing" ] && [ "$existing" != "null" ]; then
      # Comment on existing instead
      gh issue comment "$existing" --repo "$repo" --body "Duplicate occurrence from another session ($(date -u +%Y-%m-%dT%H:%M:%SZ))" >/dev/null 2>&1 || true
      bug_reporter_mark_sent "$sig"
      return 0
    fi

    # Build assignee args conditionally — issue #22: external submitters
    # don't have write perm on vietdev99/vgflow, so --assignee=vietdev99
    # always fails for them with `ReplaceActorsForAssignable` permission
    # error. Try with assignee first; on perm-related failure, retry
    # without. Drop --assignee entirely if `assignee` is empty.
    local assign_args=()
    [ -n "$assignee" ] && assign_args=(--assignee "$assignee")

    # Try issue create. If fails due to missing labels (404), auto-create + retry.
    local create_err
    create_err=$(gh issue create --repo "$repo" --title "$title" --body "$body" --label "$labels" "${assign_args[@]}" 2>&1 >/dev/null)
    if [ $? -eq 0 ]; then
      bug_reporter_mark_sent "$sig"
      return 0
    fi

    # Auto-create missing labels (one-time per session) then retry once
    if echo "$create_err" | grep -q "label.*not found"; then
      bug_reporter_ensure_labels "$repo" "$labels" >/dev/null 2>&1
      if gh issue create --repo "$repo" --title "$title" --body "$body" --label "$labels" "${assign_args[@]}" >/dev/null 2>&1; then
        bug_reporter_mark_sent "$sig"
        return 0
      fi
    fi

    # Permission error on assignment (issue #22) — retry without --assignee.
    # External submitters can still report; only assignment is sacrificed.
    if [ ${#assign_args[@]} -gt 0 ] && \
       echo "$create_err" | grep -qE "ReplaceActorsForAssignable|does not have.*permission|Resource not accessible"; then
      if gh issue create --repo "$repo" --title "$title" --body "$body" --label "$labels" >/dev/null 2>&1; then
        bug_reporter_mark_sent "$sig"
        return 0
      fi
    fi

    # gh CLI present but issue create failed (network, perms, repo missing) — keep in queue, do NOT mark sent
    echo "⚠ Bug report sig ${sig} create failed via gh: ${create_err}" >&2
    echo "  Will retry next /vg:bug-report --flush. Run: gh issue create manually if urgent." >&2
    return 1
  fi

  # gh CLI unavailable — leave bug in queue, don't lose it.
  # User opted in via consent but gh disappeared (uninstalled / PATH change / auth expired).
  echo "⚠ Bug report sig ${sig}: gh CLI not available." >&2
  echo "  Install: https://cli.github.com  OR  disable: /vg:bug-report --disable-all" >&2
  echo "  Bug kept in queue (.claude/.bug-reports-queue.jsonl) — will retry on next flush." >&2
  return 1
}

# Ensure required labels exist on repo (idempotent — safe to call repeatedly)
bug_reporter_ensure_labels() {
  local repo="$1"
  local labels_csv="$2"
  local IFS=','
  for label in $labels_csv; do
    label=$(echo "$label" | xargs)  # trim
    [ -z "$label" ] && continue
    case "$label" in
      bug-auto)     gh label create "$label" --repo "$repo" --color "d73a4a" --description "Auto-reported by vg bug-reporter" 2>/dev/null || true ;;
      needs-triage) gh label create "$label" --repo "$repo" --color "fbca04" --description "Needs human triage" 2>/dev/null || true ;;
      *)            gh label create "$label" --repo "$repo" --color "ededed" --description "vg bug-reporter label" 2>/dev/null || true ;;
    esac
  done
}

bug_reporter_mark_sent() {
  local sig="$1"
  local sent="${CONFIG_BUG_REPORTING_SENT_CACHE:-$BUG_REPORTER_DEFAULT_SENT}"
  mkdir -p "$(dirname "$sent")" 2>/dev/null || true
  echo "{\"signature\":\"${sig}\",\"sent_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" >> "$sent"
}

# Show queue contents
bug_reporter_queue_show() {
  local queue="${CONFIG_BUG_REPORTING_QUEUE:-$BUG_REPORTER_DEFAULT_QUEUE}"
  if [ ! -f "$queue" ]; then
    echo "Queue empty: $queue"
    return 0
  fi
  local count
  count=$(wc -l < "$queue" 2>/dev/null)
  echo "Queue: $queue ($count events)"
  tail -10 "$queue"
}

# Flush queue to GitHub
bug_reporter_queue_flush() {
  local queue="${CONFIG_BUG_REPORTING_QUEUE:-$BUG_REPORTER_DEFAULT_QUEUE}"
  [ -f "$queue" ] || { echo "Queue empty"; return 0; }

  local total_count sent_count=0 skip_count=0
  total_count=$(wc -l < "$queue")

  while IFS= read -r event; do
    [ -z "$event" ] && continue
    local sig
    sig=$(echo "$event" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('signature',''))" 2>/dev/null)
    if bug_reporter_dedup_check "$sig"; then
      skip_count=$((skip_count + 1))
      continue
    fi
    bug_reporter_github_submit_from_event "$event"
    sent_count=$((sent_count + 1))
  done < "$queue"

  # Rotate queue (move to .processed)
  mv "$queue" "${queue}.processed.$(date +%s)" 2>/dev/null || true

  echo "✓ Flushed: ${sent_count} sent, ${skip_count} already-sent (skipped), ${total_count} total"
}

# === Schema violation detector for dim-expander + answer-challenger ===
# Call: bug_reporter_validate_schema TYPE JSON_OUTPUT
# Example: bug_reporter_validate_schema "dim_expander" "$output_json"
bug_reporter_validate_schema() {
  local type="$1" json="$2"
  case "$type" in
    dim_expander)
      # critical_missing + nice_to_have_missing MUST be arrays of objects
      local violation
      violation=$(echo "$json" | ${PYTHON_BIN:-python3} -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    for field in ['critical_missing', 'nice_to_have_missing']:
        arr = d.get(field, [])
        if not isinstance(arr, list): continue
        for item in arr:
            if not isinstance(item, dict):
                print(f'{field} contains non-dict item: {type(item).__name__}')
                sys.exit(0)
            if 'dimension' not in item:
                print(f'{field} item missing dimension field')
                sys.exit(0)
except Exception as e:
    print(f'JSON parse error: {e}')
" 2>/dev/null)
      if [ -n "$violation" ]; then
        report_bug "dim-expander-schema" "schema_violation" "$violation" "medium"
        return 1
      fi
      ;;
    answer_challenger)
      local violation
      violation=$(echo "$json" | ${PYTHON_BIN:-python3} -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    required = ['has_issue', 'issue_kind', 'evidence', 'follow_up_question', 'proposed_alternative']
    for k in required:
        if k not in d:
            print(f'missing required field: {k}')
            sys.exit(0)
except Exception as e:
    print(f'JSON parse error: {e}')
" 2>/dev/null)
      if [ -n "$violation" ]; then
        report_bug "challenger-schema" "schema_violation" "$violation" "medium"
        return 1
      fi
      ;;
  esac
  return 0
}

# === User pushback detector ===
# Scan AskUserQuestion answer for pushback keywords, signal bug if detected.
bug_reporter_detect_pushback() {
  local user_answer="$1" context="${2:-unknown-step}"
  local keywords="nhầm|sai|bug|wrong|không đúng|không phải|phân tích sai|hiểu nhầm"

  if echo "$user_answer" | grep -qiE "$keywords"; then
    report_bug "pushback-${context}" "user_pushback" "User signaled workflow issue in step=${context}. Answer contained pushback keyword. Consider: was AI analysis wrong? Was terminology ambiguous?" "medium"
    return 1
  fi
  return 0
}
