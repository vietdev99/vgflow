---
user-invocable: true
description: "Auto-detect workflow bugs + push to GitHub issues on vietdev99/vgflow. Opt-out default, anonymous URL fallback if no gh auth."
---

<rules>
1. **Opt-out default** — first install prompts consent. User can disable via `--disable-all`.
2. **Privacy-first** — redact project paths, names, emails, phase IDs before upload.
3. **Dedup** — local sent cache + GitHub issue search by signature.
4. **Rate limit** — max 5 events per session (configurable via `config.bug_reporting.max_per_session`).
5. **3-tier send** — gh CLI (authenticated) → URL fallback (anonymous) → silent queue (if auto_send_minor=false).
6. **Severity threshold** — only immediate-send if severity >= threshold. Lower severities queued for weekly flush.
</rules>

<objective>
Auto-report workflow bugs to vietdev99/vgflow. Users help improve VG by letting AI detect issues (schema violations, helper errors, user pushback, gate loops) and report them.

Modes:
- `--flush` — send queued events now
- `--queue` — show pending local queue
- `--disable=<signature>` — suppress future reports of a specific signature
- `--disable-all` — disable entire bug reporter
- `--enable` — re-enable after disable
- `--stats` — local statistics
- `--test` — send test bug to verify setup
- Without flags → prompt consent if not yet configured, else show status
</objective>

<process>

**Source:**
```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/bug-reporter.sh"
```

<step name="0_parse">
Parse flags:
```bash
MODE="status"
SIG=""
for arg in $ARGUMENTS; do
  case "$arg" in
    --flush)          MODE="flush" ;;
    --queue)          MODE="queue" ;;
    --disable=*)      MODE="disable"; SIG="${arg#*=}" ;;
    --disable-all)    MODE="disable-all" ;;
    --enable)         MODE="enable" ;;
    --stats)          MODE="stats" ;;
    --test)           MODE="test" ;;
  esac
done
```
</step>

<step name="1_dispatch">

### Mode: `status` (default)

```bash
bug_reporter_consent_prompt  # prompts if not yet configured
if bug_reporter_enabled; then
  echo "✓ Bug reporting enabled"
  count=$(bug_reporter_session_count)
  echo "  Session events: ${count}"
  local queue="${CONFIG_BUG_REPORTING_QUEUE:-.claude/.bug-reports-queue.jsonl}"
  if [ -f "$queue" ]; then
    echo "  Queued (pending flush): $(wc -l < "$queue")"
  fi
  local sent="${CONFIG_BUG_REPORTING_SENT_CACHE:-.claude/.bug-reports-sent.jsonl}"
  if [ -f "$sent" ]; then
    echo "  Total sent: $(wc -l < "$sent")"
  fi
else
  echo "⚠ Bug reporting disabled. Enable: /vg:bug-report --enable"
fi
```

### Mode: `flush`

```bash
bug_reporter_queue_flush
```

### Mode: `queue`

```bash
bug_reporter_queue_show
```

### Mode: `disable=SIG`

```bash
local disabled="${CONFIG_BUG_REPORTING_DISABLED:-.claude/.bug-reports-disabled.txt}"
mkdir -p "$(dirname "$disabled")"
echo "$SIG" >> "$disabled"
echo "✓ Signature $SIG suppressed. Future reports ignored."
```

### Mode: `disable-all`

```bash
${PYTHON_BIN} -c "
import re
cfg = '.claude/vg.config.md'
txt = open(cfg, encoding='utf-8').read()
txt = re.sub(r'(bug_reporting:\n  enabled:)\s*true', r'\1 false', txt)
open(cfg, 'w', encoding='utf-8').write(txt)
print('✓ Bug reporting disabled. Existing queue preserved but not sent.')
"
```

### Mode: `enable`

```bash
${PYTHON_BIN} -c "
import re
cfg = '.claude/vg.config.md'
txt = open(cfg, encoding='utf-8').read()
txt = re.sub(r'(bug_reporting:\n  enabled:)\s*false', r'\1 true', txt)
open(cfg, 'w', encoding='utf-8').write(txt)
print('✓ Bug reporting enabled. Run /vg:bug-report --flush to send queued events.')
"
```

### Mode: `stats`

```bash
echo "=== Bug Reporter Stats ==="
local queue_count=0 sent_count=0 disabled_count=0
[ -f "${CONFIG_BUG_REPORTING_QUEUE:-.claude/.bug-reports-queue.jsonl}" ] && queue_count=$(wc -l < "${CONFIG_BUG_REPORTING_QUEUE:-.claude/.bug-reports-queue.jsonl}")
[ -f "${CONFIG_BUG_REPORTING_SENT_CACHE:-.claude/.bug-reports-sent.jsonl}" ] && sent_count=$(wc -l < "${CONFIG_BUG_REPORTING_SENT_CACHE:-.claude/.bug-reports-sent.jsonl}")
[ -f "${CONFIG_BUG_REPORTING_DISABLED:-.claude/.bug-reports-disabled.txt}" ] && disabled_count=$(wc -l < "${CONFIG_BUG_REPORTING_DISABLED:-.claude/.bug-reports-disabled.txt}")
echo "  Queued: $queue_count"
echo "  Sent: $sent_count"
echo "  Disabled signatures: $disabled_count"
echo ""
echo "Top 5 most-reported types (from sent cache):"
[ -f "${CONFIG_BUG_REPORTING_SENT_CACHE}" ] && ${PYTHON_BIN} -c "
import json, collections
from pathlib import Path
p = Path('${CONFIG_BUG_REPORTING_SENT_CACHE:-.claude/.bug-reports-sent.jsonl}')
if p.exists():
    types = [json.loads(l).get('signature','') for l in p.read_text().splitlines() if l]
    for t, c in collections.Counter(types).most_common(5):
        print(f'  - {t}: {c}')
"
```

### Mode: `test`

```bash
echo "=== Test bug report (dry run) ==="
report_bug "test-$(date +%s)" "test_event" "This is a test event from /vg:bug-report --test" "minor"
echo "Check: /vg:bug-report --queue"
echo "Send: /vg:bug-report --flush"
```
</step>

</process>

<success_criteria>
- `status` mode prompts consent if config missing, shows state otherwise
- `flush` sends queue via gh CLI or URL fallback
- `disable=SIG` adds signature to disabled list, suppresses future reports
- `disable-all` / `enable` toggle config.bug_reporting.enabled
- `stats` shows queued/sent/disabled counts + top types
- `test` creates sample event end-to-end
</success_criteria>
