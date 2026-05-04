---
name: vg:setup-mobile
description: Install mobile E2E tooling — adb, Maestro, Android SDK, AVD — cross-platform (macOS/Linux/Windows)
argument-hint: "[--tools=adb,maestro,sdk,avd] [--avd=<name>] [--api=<level>]"
allowed-tools:
  - Read
  - Bash
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "setup_mobile.started"
    - event_type: "setup_mobile.completed"
---

<rules>
1. **Idempotent** — re-running is safe. Tools already on PATH are detected and skipped.
2. **No admin required** — installs to `$HOME/mobile-env` (user scope).
3. **OS-aware** — different download URLs for macOS / Linux / Windows msys. iOS simulator unsupported outside macOS; script does NOT attempt it.
4. **No hardcoded device names** — AVD name/API/image all overridable via env (`VG_AVD_NAME`, `VG_AVD_API`, `VG_SDK_IMAGE_TAG`) or CLI args.
5. **Activate only, don't persist** — script emits `export PATH=...` lines for user to paste into shell profile. Never auto-modifies `~/.bashrc` / `~/.zshrc` (respects user autonomy).
6. **Profile-relevant** — intended for projects where `profile ∈ mobile-*`. Safe to run on web projects but wastes disk (~5GB Android SDK).
</rules>

<objective>
One-shot installer for the mobile toolchain VG workflow needs:

| Tool | Purpose | Size |
|------|---------|------|
| adb (platform-tools) | Talk to emulator/device | ~10MB |
| Maestro CLI | Drive Android/iOS UI for `phase2_mobile_discovery` + `5c_mobile_flow` | ~200MB |
| Android SDK cmdline-tools | `sdkmanager`, `avdmanager` | ~150MB |
| Emulator + system-image | Local Android runtime | ~3-5GB |
| AVD | Ready-made emulator device (default: Pixel 7 API 34) | — |

After success, `python maestro-mcp.py check-prereqs` reports `android_flows: true`.
iOS steps still require macOS or a cloud provider — see README "Mobile profiles (V1)" section.
</objective>

<process>

<step name="0_load_config">
Follow `.claude/commands/vg/_shared/config-loader.md` to resolve `$REPO_ROOT`, `$PYTHON_BIN`.

```bash
SCRIPT="${REPO_ROOT}/.claude/scripts/setup-mobile-env.sh"
if [ ! -x "$SCRIPT" ]; then
  # Fallback to vgflow canonical if .claude/ mirror missing (fresh install)
  SCRIPT="${REPO_ROOT}/vgflow/scripts/setup-mobile-env.sh"
fi
if [ ! -f "$SCRIPT" ]; then
  echo "⛔ setup-mobile-env.sh not found. Run install.sh first or update vgflow."
  exit 1
fi
```
</step>

<step name="1_parse_args">
Forward all slash-command args to the shell script:

```bash
# Args from the user — pass-through unchanged.
ARGS="$ARGUMENTS"
```

Common patterns:
- `/vg:setup-mobile` — install everything (default)
- `/vg:setup-mobile --tools=adb,maestro` — partial
- `/vg:setup-mobile --avd=Nexus_6P_API_33 --api=33` — custom device (via env prefix)
- `/vg:setup-mobile --help` — show full help
</step>

<step name="2_probe_current_state">
Before running the installer, show user what's currently missing so they know what to expect:

```bash
echo "=== Current mobile tooling state ==="
for tool in java adb maestro emulator sdkmanager avdmanager; do
  path=$(command -v "$tool" 2>/dev/null || true)
  if [ -n "$path" ]; then
    echo "  ✓ $tool  ($path)"
  else
    echo "  ✗ $tool  (not on PATH)"
  fi
done

# Also consult the VG wrapper's view
if [ -f "${REPO_ROOT}/.claude/scripts/maestro-mcp.py" ]; then
  echo ""
  echo "=== VG wrapper view ==="
  ${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/maestro-mcp.py" --json check-prereqs \
    | ${PYTHON_BIN} -c "import json,sys;d=json.load(sys.stdin);print(f'  host_os: {d[\"host_os\"]}');print(f'  android_flows: {d[\"capabilities\"][\"android_flows\"]}');print(f'  ios_flows: {d[\"capabilities\"][\"ios_flows\"]}')"
fi
echo ""
```
</step>

<step name="3_run_installer">
Invoke the script with user args. The script itself:
- Detects host OS (darwin/linux/windows-msys)
- Checks `java` (bails out with install hint if missing — user must handle manually)
- Downloads adb + Maestro + SDK cmdline-tools to `~/mobile-env/`
- Accepts SDK licenses (`yes | sdkmanager --licenses`)
- Installs `emulator`, `platform-tools`, `platforms;android-N`, `system-images;android-N;google_apis;x86_64`
- Creates AVD `${VG_AVD_NAME}` (default `Pixel_7_API_34`)
- Emits activation hint (`export PATH=...`) at the end

```bash
bash "$SCRIPT" $ARGS
RC=$?
if [ $RC -ne 0 ]; then
  echo ""
  echo "⛔ Setup failed. Re-run with --help for tool-specific subset flags."
  exit $RC
fi
```

**Expected download size**: 150MB (cmdline-tools) → extract → then sdkmanager pulls ~3-5GB system-image. **Budget 5-15 minutes** depending on network.
</step>

<step name="4_verify">
Activate the newly-installed tooling for this shell session and re-probe:

```bash
VG_MOBILE_DIR="${VG_MOBILE_DIR:-$HOME/mobile-env}"
export ANDROID_HOME="$VG_MOBILE_DIR/android-sdk"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/emulator:$VG_MOBILE_DIR/platform-tools:$VG_MOBILE_DIR/maestro/bin:$PATH"

echo ""
echo "=== Post-install verification ==="
adb --version     2>&1 | head -1 || echo "  ⚠ adb not active in this shell"
maestro --version 2>&1 | head -1 || echo "  ⚠ maestro not active"
emulator -list-avds 2>&1 | head -5

echo ""
echo "=== VG wrapper re-check ==="
${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/maestro-mcp.py" --json check-prereqs \
  | ${PYTHON_BIN} -m json.tool
```

Show user the final `android_flows: true` state — that's the green light for `/vg:review` mobile discovery + `/vg:test` Maestro flows.
</step>

<step name="5_next_steps">
Print a short playbook of what to do next:

```
Mobile tooling ready. Next:

  1. Activate PATH persistently (copy the 2 export lines above into ~/.bashrc / ~/.zshrc)
  2. Boot the emulator:
        emulator -avd ${VG_AVD_NAME:-Pixel_7_API_34} &
  3. Confirm it's online:
        adb devices
  4. Install your app (one of):
        npx expo start --android          # Expo RN — installs Expo Go
        adb install path/to/app-debug.apk # pre-built APK
  5. Smoke-test Maestro:
        maestro test path/to/flow.maestro.yaml

For the full VG mobile pipeline, see vgflow/README.md section "Mobile profiles (V1)".
```
</step>

</process>

<success_criteria>
- adb, maestro, emulator, sdkmanager, avdmanager all on PATH after activation
- `maestro-mcp.py check-prereqs` → `android_flows: true`
- AVD `${VG_AVD_NAME}` listed by `emulator -list-avds`
- Installer is idempotent — re-running skips already-present tools
- No `~/.bashrc` / `~/.zshrc` modified by the installer (user does it manually)
- Works on macOS, Linux, Windows msys/Git Bash without code branching in VG workflow files
</success_criteria>
