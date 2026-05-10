<!-- v2.73.0 T6-T10 extraction — verbatim step blocks from commands/vg/update.md -->
<!-- Group: version-and-changelog | Steps: 2_version_compare, 3_changelog_preview, 4_breaking_gate -->

<process>

<step name="2_version_compare">
```bash
CHECK_OUTPUT="$(python3 "$HELPER" check --repo "$REPO")"
RC=$?
if [ $RC -ne 0 ]; then
  echo "Check failed (network offline or API error):"
  echo "$CHECK_OUTPUT"
  exit $RC
fi

INSTALLED="$(printf '%s' "$CHECK_OUTPUT" | grep -oE 'current=[^ ]+' | head -n1 | sed 's/^current=//')"
LATEST="$(printf   '%s' "$CHECK_OUTPUT" | grep -oE 'latest=[^ ]+'  | head -n1 | sed 's/^latest=//')"
STATE="$(printf    '%s' "$CHECK_OUTPUT" | grep -oE 'state=[^ ]+'   | head -n1 | sed 's/^state=//')"

echo "installed=${INSTALLED} latest=${LATEST} state=${STATE}"

case "$STATE" in
  up-to-date)
    echo "Already on v${INSTALLED}. Nothing to do."
    exit 0
    ;;
  ahead-of-release)
    echo "Local v${INSTALLED} is ahead of latest release v${LATEST} (dev build?). Nothing to do."
    exit 0
    ;;
  update-available)
    echo "Update available: v${INSTALLED} -> v${LATEST}"
    ;;
  *)
    echo "Unknown state: ${STATE}"
    exit 2
    ;;
esac
```
</step>

<step name="3_changelog_preview">
```bash
echo ""
echo "--- Changelog preview (v${INSTALLED} -> v${LATEST}) ---"
CHANGELOG_RAW="$(curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/CHANGELOG.md" 2>/dev/null || true)"

if [ -z "$CHANGELOG_RAW" ]; then
  echo "(CHANGELOG.md not reachable; skipping preview)"
else
  printf '%s\n' "$CHANGELOG_RAW" | INSTALLED="$INSTALLED" LATEST="$LATEST" python3 -c "
import os, re, sys

text = sys.stdin.read()
installed = os.environ.get('INSTALLED', '0.0.0')
latest    = os.environ.get('LATEST', '0.0.0')

def vt(v):
    try:
        return tuple(int(x) for x in v.lstrip('v').split('.'))
    except Exception:
        return (0, 0, 0)

inst_t = vt(installed)
late_t = vt(latest)

# v2.38.1 fix: support both '## v2.38.0' (current VG format) and
# '## [2.38.0]' (legacy keep-a-changelog format). Prior regex only
# matched bracketed form → preview always empty for v2.32+.
pattern = re.compile(
    r'^## (?:\[)?v?(\d+\.\d+\.\d+)(?:\])?[^\n]*\n.*?(?=^## (?:\[)?v?\d+\.\d+\.\d+|\Z)',
    re.S | re.M,
)
shown = False
for m in pattern.finditer(text):
    ver = m.group(1)
    t = vt(ver)
    if t > inst_t and t <= late_t:
        sys.stdout.write(m.group(0).rstrip() + '\n\n')
        shown = True
if not shown:
    sys.stdout.write('(no changelog entries between versions)\n')
"
fi
echo "-------------------------------------------------"
```

Then ask via AskUserQuestion:
- **question:** `"Proceed with update v${INSTALLED} -> v${LATEST}?"`
- **options:** `["Yes, update now", "No, cancel"]`

If user picks **No, cancel**, run:
```bash
echo "Cancelled. No changes applied."
exit 0
```
</step>

<step name="4_breaking_gate">
```bash
MAJOR_INSTALLED="$(printf '%s' "$INSTALLED" | cut -d. -f1)"
MAJOR_LATEST="$(printf    '%s' "$LATEST"    | cut -d. -f1)"

# Normalize non-numeric to 0
case "$MAJOR_INSTALLED" in *[!0-9]*|'') MAJOR_INSTALLED=0 ;; esac
case "$MAJOR_LATEST"    in *[!0-9]*|'') MAJOR_LATEST=0    ;; esac

# Additional deep-compat scan — catches breaking changes WITHIN a major
# (renamed step markers, dropped contract fields, removed scripts, etc.)
# compat-check.py reads latest RELEASE.md / CHANGELOG, grep against installed
# skill files, surface anything user needs to know regardless of major bump.
COMPAT_CHECK=".claude/scripts/compat-check.py"
if [ -f "$COMPAT_CHECK" ]; then
  echo ""
  echo "━━━ Deep compat scan (${INSTALLED} → ${LATEST}) ━━━"
  ${PYTHON_BIN:-python3} "$COMPAT_CHECK" \
    --from "$INSTALLED" --to "$LATEST" 2>&1 | head -50 \
    || echo "(compat-check returned non-zero — review output before proceeding)"
fi

if [ "$MAJOR_LATEST" -gt "$MAJOR_INSTALLED" ] && [ "$INSTALLED" != "0.0.0" ]; then
  MIG="migrations/v${MAJOR_INSTALLED}_to_v${MAJOR_LATEST}.md"
  echo ""
  echo "=== BREAKING CHANGE DETECTED ==="
  echo "  v${MAJOR_INSTALLED}.x -> v${MAJOR_LATEST}.x"
  echo ""
  echo "--- Migration doc: ${MIG} ---"
  curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/${MIG}" 2>/dev/null \
    || echo "(no migration doc found at that path -- review CHANGELOG manually)"
  echo "----------------------------"
  echo ""

  if ! printf '%s' "$ARGS" | grep -qE -- '(^|[[:space:]])--accept-breaking([[:space:]]|$)'; then
    echo "Breaking change requires opt-in. Re-run with --accept-breaking to proceed."
    exit 1
  fi
  echo "User opted in via --accept-breaking. Proceeding."
fi
```
</step>

</process>
