#!/usr/bin/env bash
# VG mobile environment installer — cross-platform (macOS / Linux / Windows msys).
# Installs adb, Maestro, Android SDK, and creates a default AVD.
# Idempotent: skips tools that are already on PATH.
# NO hardcoded device names or paths — everything is config-driven or user-overridable.
#
# Usage:
#   bash setup-mobile-env.sh                       # install all tools (no boot)
#   bash setup-mobile-env.sh --tools=adb           # install specific subset
#   bash setup-mobile-env.sh --boot                # additionally launch emulator + wait
#   bash setup-mobile-env.sh --smoke               # additionally run Maestro smoke test
#   bash setup-mobile-env.sh --with-expo-go        # additionally install Expo Go APK
#   bash setup-mobile-env.sh --boot --smoke --with-expo-go   # full end-to-end
#   bash setup-mobile-env.sh --help
#
# Env overrides:
#   VG_MOBILE_DIR       install root (default: ~/mobile-env)
#   VG_AVD_NAME         AVD name to create (default: Pixel_7_API_34)
#   VG_AVD_API          Android API level (default: 34)
#   VG_AVD_DEVICE       device preset (default: pixel_7)
#   VG_SDK_IMAGE_TAG    system-image tag (default: google_apis;x86_64)
#   VG_SKIP_AVD=1       skip AVD creation even if sdk+emulator installed
#   VG_BOOT_TIMEOUT     seconds to wait for emulator boot (default: 240)

set -u

# ---------- constants ----------
VG_MOBILE_DIR="${VG_MOBILE_DIR:-$HOME/mobile-env}"
VG_AVD_NAME="${VG_AVD_NAME:-Pixel_7_API_34}"
VG_AVD_API="${VG_AVD_API:-34}"
VG_AVD_DEVICE="${VG_AVD_DEVICE:-pixel_7}"
VG_SDK_IMAGE_TAG="${VG_SDK_IMAGE_TAG:-google_apis;x86_64}"
VG_SKIP_AVD="${VG_SKIP_AVD:-0}"
VG_BOOT_TIMEOUT="${VG_BOOT_TIMEOUT:-240}"

SCRIPT_VERSION="1.1"
DO_BOOT=0
DO_SMOKE=0
DO_EXPO_GO=0
EMU_PID=""

# ---------- OS detection ----------
detect_os() {
  case "$(uname -s 2>/dev/null)" in
    Darwin*)                echo "darwin" ;;
    Linux*)                 echo "linux" ;;
    MINGW*|MSYS*|CYGWIN*)   echo "windows" ;;
    *)                      echo "unknown" ;;
  esac
}
HOST_OS="$(detect_os)"

# ---------- logging ----------
ok()   { printf "\033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "\033[33m⚠\033[0m %s\n" "$*"; }
err()  { printf "\033[31m✗\033[0m %s\n" "$*" >&2; }
info() { printf "  %s\n" "$*"; }

# ---------- arg parsing ----------
INSTALL_ALL=1
WANTED_TOOLS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h)
      cat <<EOF
setup-mobile-env.sh v${SCRIPT_VERSION} — VG mobile tooling installer

Tools (select with --tools=<csv>): jdk, adb, maestro, sdk, avd, all (default)

Post-install flags (opt-in):
  --boot           launch emulator in background + wait for boot_completed
  --smoke          --boot + run Maestro smoke test (launch Settings, screenshot)
  --with-expo-go   --boot + download + adb-install latest Expo Go APK

Examples:
  bash setup-mobile-env.sh                                 # install tools only
  bash setup-mobile-env.sh --boot                          # tools + start emulator
  bash setup-mobile-env.sh --smoke                         # tools + boot + Maestro smoke
  bash setup-mobile-env.sh --boot --with-expo-go --smoke   # full end-to-end
  bash setup-mobile-env.sh --tools=adb,maestro             # partial install
  bash setup-mobile-env.sh --help

Env overrides:
  VG_MOBILE_DIR    (default ~/mobile-env)
  VG_AVD_NAME      (default Pixel_7_API_34)
  VG_AVD_API       (default 34)
  VG_AVD_DEVICE    (default pixel_7)
  VG_SDK_IMAGE_TAG (default "google_apis;x86_64")
  VG_SKIP_AVD=1    skip AVD creation even if sdk+emulator installed
  VG_BOOT_TIMEOUT  (default 240) seconds to wait for emulator boot

JDK auto-install: brew (macOS) / apt|dnf (Linux) / winget (Windows).
Falls back to manual install hint if package manager unavailable.
Uses public download URLs for adb, Maestro, Android SDK. Installs to \$HOME — no admin.
Windows: checks Hyper-V / WHPX presence (advisory only — can't enable without admin).
EOF
      exit 0 ;;
    --tools=*)
      INSTALL_ALL=0
      IFS=',' read -r -a WANTED_TOOLS <<< "${1#--tools=}"
      ;;
    --boot)          DO_BOOT=1 ;;
    --smoke)         DO_BOOT=1; DO_SMOKE=1 ;;
    --with-expo-go)  DO_BOOT=1; DO_EXPO_GO=1 ;;
    *)
      err "Unknown arg: $1 (see --help)"
      exit 2 ;;
  esac
  shift
done

want() {
  [ $INSTALL_ALL -eq 1 ] && return 0
  local t="$1"
  for w in "${WANTED_TOOLS[@]}"; do
    [ "$w" = "$t" ] && return 0
    [ "$w" = "all" ] && return 0
  done
  return 1
}

# ---------- shared helpers ----------
ensure_dir() { mkdir -p "$1"; }

download() {
  local url="$1" out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$out" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$out" "$url"
  else
    err "neither curl nor wget available — cannot download $url"
    return 1
  fi
}

# Return path-to-tool on PATH, or empty string.
which_tool() { command -v "$1" 2>/dev/null || true; }

# ---------- JDK auto-install (required by Maestro + Android) ----------
step_jdk() {
  want jdk || return 0
  local java_bin
  java_bin="$(which_tool java)"
  if [ -n "$java_bin" ]; then
    local ver
    ver="$(java --version 2>&1 | head -1)"
    ok "Java found: ${ver}"
    return 0
  fi
  info "Java not found. Attempting auto-install (JDK 21)..."
  case "$HOST_OS" in
    darwin)
      if command -v brew >/dev/null 2>&1; then
        brew install --cask temurin@21 && { ok "JDK 21 installed via Homebrew"; return 0; }
      fi
      warn "Install manually: brew install --cask temurin@21 (or https://adoptium.net/)"
      return 1 ;;
    linux)
      if command -v apt-get >/dev/null 2>&1; then
        if sudo -n true 2>/dev/null; then
          sudo apt-get update -qq && sudo apt-get install -y openjdk-21-jdk \
            && { ok "JDK 21 installed via apt"; return 0; }
        else
          warn "sudo password required. Run: sudo apt-get install -y openjdk-21-jdk"
        fi
      elif command -v dnf >/dev/null 2>&1; then
        warn "Run: sudo dnf install -y java-21-openjdk-devel"
      fi
      return 1 ;;
    windows)
      if command -v winget >/dev/null 2>&1; then
        # User-scope install, no admin required
        winget install --id EclipseAdoptium.Temurin.21.JDK \
          --accept-source-agreements --accept-package-agreements --silent 2>&1 \
          | tail -5
        # winget may succeed without refreshing PATH in this shell — verify via which again
        java_bin="$(which_tool java)"
        if [ -n "$java_bin" ]; then
          ok "JDK 21 installed via winget"
          return 0
        fi
        warn "JDK installed but not on PATH in this shell. Open a new terminal and re-run."
        return 1
      fi
      warn "Install: winget install EclipseAdoptium.Temurin.21.JDK"
      return 1 ;;
    *)
      warn "Install JDK 21 manually from https://adoptium.net/"
      return 1 ;;
  esac
}

# ---------- adb (Android platform-tools) ----------
PT_DIR="$VG_MOBILE_DIR/platform-tools"
step_adb() {
  want adb || return 0
  if [ -x "$PT_DIR/adb" ] || [ -x "$PT_DIR/adb.exe" ] || [ -n "$(which_tool adb)" ]; then
    ok "adb already available ($(which_tool adb 2>/dev/null || echo "$PT_DIR"))"
    return 0
  fi
  info "Installing platform-tools to $PT_DIR"
  local pt_url
  case "$HOST_OS" in
    darwin)  pt_url="https://dl.google.com/android/repository/platform-tools-latest-darwin.zip" ;;
    linux)   pt_url="https://dl.google.com/android/repository/platform-tools-latest-linux.zip" ;;
    windows) pt_url="https://dl.google.com/android/repository/platform-tools-latest-windows.zip" ;;
    *)       err "Unsupported OS for adb auto-install. Download manually: https://developer.android.com/tools/releases/platform-tools"
             return 1 ;;
  esac
  ensure_dir "$VG_MOBILE_DIR/_dl"
  local zip="$VG_MOBILE_DIR/_dl/platform-tools.zip"
  download "$pt_url" "$zip" || { err "adb download failed"; return 1; }
  if ! command -v unzip >/dev/null 2>&1; then
    err "unzip required but missing. Install unzip and retry."
    return 1
  fi
  unzip -q "$zip" -d "$VG_MOBILE_DIR/"
  rm -rf "$VG_MOBILE_DIR/_dl"
  ok "adb installed: $PT_DIR/adb ($(${PT_DIR}/adb --version 2>&1 | head -1))"
}

# ---------- Maestro CLI ----------
MAESTRO_DIR="$VG_MOBILE_DIR/maestro"
step_maestro() {
  want maestro || return 0
  if [ -x "$MAESTRO_DIR/bin/maestro" ] || [ -n "$(which_tool maestro)" ]; then
    ok "Maestro already available ($(which_tool maestro 2>/dev/null || echo "$MAESTRO_DIR"))"
    return 0
  fi
  info "Installing Maestro to $MAESTRO_DIR"
  ensure_dir "$VG_MOBILE_DIR/_dl"
  local zip="$VG_MOBILE_DIR/_dl/maestro.zip"
  local url="https://github.com/mobile-dev-inc/maestro/releases/latest/download/maestro.zip"
  download "$url" "$zip" || { err "Maestro download failed"; return 1; }
  if ! command -v unzip >/dev/null 2>&1; then
    err "unzip required but missing. Install unzip and retry."
    return 1
  fi
  unzip -q "$zip" -d "$VG_MOBILE_DIR/_dl/"
  ensure_dir "$MAESTRO_DIR"
  cp -rf "$VG_MOBILE_DIR/_dl/maestro/." "$MAESTRO_DIR/"
  rm -rf "$VG_MOBILE_DIR/_dl"
  chmod +x "$MAESTRO_DIR/bin/maestro" 2>/dev/null || true
  ok "Maestro installed: $MAESTRO_DIR/bin/maestro"
}

# ---------- Android SDK (cmdline-tools + emulator + platform + system-image) ----------
SDK_DIR="$VG_MOBILE_DIR/android-sdk"
step_sdk() {
  want sdk || return 0
  if [ -d "$SDK_DIR/cmdline-tools/latest/bin" ] && [ -d "$SDK_DIR/emulator" ]; then
    ok "Android SDK already installed at $SDK_DIR"
    export ANDROID_HOME="$SDK_DIR"
    return 0
  fi
  info "Installing Android SDK to $SDK_DIR ($([ "$HOST_OS" = "windows" ] && echo "~150MB cmdline + 5GB total" || echo "~150MB cmdline + 3-5GB total"))"
  ensure_dir "$SDK_DIR/cmdline-tools"
  local ct_url
  case "$HOST_OS" in
    darwin)  ct_url="https://dl.google.com/android/repository/commandlinetools-mac-13114758_latest.zip" ;;
    linux)   ct_url="https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip" ;;
    windows) ct_url="https://dl.google.com/android/repository/commandlinetools-win-13114758_latest.zip" ;;
    *)       err "Unsupported OS for Android SDK. See https://developer.android.com/studio#command-line-tools-only"
             return 1 ;;
  esac
  local zip="$SDK_DIR/_cmdline.zip"
  download "$ct_url" "$zip" || { err "cmdline-tools download failed"; return 1; }
  unzip -q "$zip" -d "$SDK_DIR/_dl"
  if [ -d "$SDK_DIR/_dl/cmdline-tools" ]; then
    # cmdline-tools zip contains top-level cmdline-tools/ → move to latest/
    if [ -d "$SDK_DIR/cmdline-tools/latest" ]; then
      rm -rf "$SDK_DIR/cmdline-tools/latest"
    fi
    mv "$SDK_DIR/_dl/cmdline-tools" "$SDK_DIR/cmdline-tools/latest"
  fi
  rm -rf "$SDK_DIR/_dl" "$zip"
  export ANDROID_HOME="$SDK_DIR"

  # sdkmanager varies by OS: .bat on Windows (via bash call), .sh on unix
  local SDKMGR
  if [ -x "$SDK_DIR/cmdline-tools/latest/bin/sdkmanager" ]; then
    SDKMGR="$SDK_DIR/cmdline-tools/latest/bin/sdkmanager"
  else
    SDKMGR="$SDK_DIR/cmdline-tools/latest/bin/sdkmanager.bat"
  fi
  if [ ! -f "$SDKMGR" ]; then
    err "sdkmanager not found at $SDKMGR after extraction"
    return 1
  fi

  info "Accepting SDK licenses (auto-yes)..."
  yes 2>/dev/null | "$SDKMGR" --licenses >/dev/null 2>&1 || true

  info "Installing emulator, platform-tools, platform-android-${VG_AVD_API}, system-image..."
  "$SDKMGR" --install \
    "emulator" \
    "platform-tools" \
    "platforms;android-${VG_AVD_API}" \
    "system-images;android-${VG_AVD_API};${VG_SDK_IMAGE_TAG}" >/dev/null 2>&1 \
    || { err "SDK component install failed. Run manually: $SDKMGR --install ..."; return 1; }

  ok "Android SDK installed at $SDK_DIR"
  info "  cmdline-tools: $SDK_DIR/cmdline-tools/latest/bin/"
  info "  emulator:      $SDK_DIR/emulator/emulator$([ "$HOST_OS" = "windows" ] && echo ".exe" || echo "")"
}

# ---------- AVD creation ----------
step_avd() {
  want avd || return 0
  [ "$VG_SKIP_AVD" = "1" ] && { info "VG_SKIP_AVD=1 → skipping AVD creation"; return 0; }
  export ANDROID_HOME="${ANDROID_HOME:-$SDK_DIR}"
  local AVDMGR
  if [ -x "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" ]; then
    AVDMGR="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager"
  else
    AVDMGR="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager.bat"
  fi
  if [ ! -f "$AVDMGR" ]; then
    warn "avdmanager missing — install SDK first (--tools=sdk)"
    return 1
  fi
  if "$AVDMGR" list avd 2>/dev/null | grep -q "Name: ${VG_AVD_NAME}"; then
    ok "AVD '${VG_AVD_NAME}' already exists"
    return 0
  fi
  info "Creating AVD: ${VG_AVD_NAME} (api ${VG_AVD_API}, device ${VG_AVD_DEVICE})"
  echo "no" | "$AVDMGR" create avd \
    -n "$VG_AVD_NAME" \
    -k "system-images;android-${VG_AVD_API};${VG_SDK_IMAGE_TAG}" \
    --device "$VG_AVD_DEVICE" \
    --force >/dev/null 2>&1 \
    || { err "AVD creation failed"; return 1; }
  ok "AVD created: ${VG_AVD_NAME}"
}

# ---------- HAXM / WHPX hardware-accel advisory (Windows only) ----------
step_accel_check() {
  [ "$HOST_OS" = "windows" ] || return 0
  # We can't enable WHPX / Hyper-V without admin. Just inform.
  local hv
  hv="$(powershell -NoProfile -Command "(Get-WmiObject Win32_ComputerSystem).HypervisorPresent" 2>/dev/null | tr -d '\r' | head -1)"
  if [ "$hv" = "True" ]; then
    ok "Hypervisor detected (emulator will use hardware acceleration)"
  else
    warn "Hypervisor NOT detected — emulator will run in software mode (slow boot)."
    info "Options to enable hardware accel:"
    info "  (1) Windows 11 / Win10 Pro: enable 'Windows Hypervisor Platform' in"
    info "      'Turn Windows features on or off' (needs admin + reboot)"
    info "  (2) Install Intel HAXM via Android Studio SDK Manager (Intel CPUs only)"
    info "  (3) Continue anyway — emulator still works, just slower"
  fi
}

# ---------- Activate PATH for post-install steps in this shell ----------
activate_path() {
  export ANDROID_HOME="$SDK_DIR"
  local ct="$SDK_DIR/cmdline-tools/latest/bin"
  local em="$SDK_DIR/emulator"
  local pt="$PT_DIR"
  local mt="$MAESTRO_DIR/bin"
  export PATH="$ct:$em:$pt:$mt:$PATH"
}

# ---------- Boot emulator in background + wait for boot_completed ----------
step_boot() {
  [ $DO_BOOT -eq 1 ] || return 0
  activate_path
  if ! command -v emulator >/dev/null 2>&1; then
    err "emulator not on PATH after activation — SDK install broken?"
    return 1
  fi
  if ! command -v adb >/dev/null 2>&1; then
    err "adb not on PATH after activation"
    return 1
  fi
  # Already booted?
  if adb devices 2>/dev/null | grep -qE 'emulator-[0-9]+\s+device'; then
    if [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; then
      ok "Emulator already running and booted"
      return 0
    fi
  fi
  info "Launching emulator '${VG_AVD_NAME}' in background..."
  # -no-snapshot: clean boot. -no-audio: Git Bash sometimes has no audio subsystem.
  # -no-boot-anim: faster boot.
  nohup emulator -avd "$VG_AVD_NAME" -no-snapshot -no-boot-anim -no-audio \
    > "$VG_MOBILE_DIR/emulator.log" 2>&1 &
  EMU_PID=$!
  info "  pid=$EMU_PID, log: $VG_MOBILE_DIR/emulator.log"
  info "Waiting up to ${VG_BOOT_TIMEOUT}s for boot_completed..."
  local start_ts=$SECONDS
  until [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do
    if [ $(( SECONDS - start_ts )) -ge "$VG_BOOT_TIMEOUT" ]; then
      err "Emulator did not finish booting within ${VG_BOOT_TIMEOUT}s."
      err "Check $VG_MOBILE_DIR/emulator.log for details."
      return 1
    fi
    sleep 3
  done
  # Ensure package manager + input subsystems are truly ready
  adb shell input keyevent 82 >/dev/null 2>&1 || true
  ok "Emulator booted ($(( SECONDS - start_ts ))s)"
  adb devices 2>&1 | sed -n '2,$p' | sed 's/^/     /'
}

# ---------- Download + install Expo Go APK via adb ----------
step_expo_go() {
  [ $DO_EXPO_GO -eq 1 ] || return 0
  activate_path
  if ! command -v adb >/dev/null 2>&1; then
    err "adb missing"
    return 1
  fi
  if ! adb devices 2>/dev/null | grep -qE '(emulator-[0-9]+|[A-Za-z0-9]+)\s+device'; then
    err "No Android device connected. Run with --boot or plug in a USB device first."
    return 1
  fi
  # Already installed?
  if adb shell pm list packages 2>/dev/null | grep -q 'host.exp.exponent'; then
    ok "Expo Go already installed on device"
    return 0
  fi
  info "Fetching latest Expo Go APK URL..."
  local api_url="https://exp.host/--/api/v2/versions/latest"
  local meta_file="$VG_MOBILE_DIR/_expo_meta.json"
  download "$api_url" "$meta_file" || { err "Expo metadata fetch failed"; return 1; }
  local apk_url
  # Feed metadata via stdin — avoids Windows msys path translation issues
  # (/c/Users/... vs C:/Users/...) when Python Path() parses the filename.
  apk_url=$(cat "$meta_file" | ${PYTHON_BIN:-python} -c "
import json, sys
d = json.load(sys.stdin)
# Expo API schema (2026): {data: {androidUrl: '...', androidVersion: '...'}}
# Older schemas used top-level androidClientUrl.
data = d.get('data', d)
print(data.get('androidUrl') or data.get('androidClientUrl') or '')
" 2>/dev/null)
  rm -f "$meta_file"
  if [ -z "$apk_url" ]; then
    err "Could not extract androidUrl from Expo API response (tried data.androidUrl, androidClientUrl)"
    return 1
  fi
  info "  URL: $apk_url"
  local apk_file="$VG_MOBILE_DIR/ExpoGo.apk"
  download "$apk_url" "$apk_file" || { err "APK download failed"; return 1; }
  info "  downloaded: $(du -h "$apk_file" | cut -f1)"
  info "Installing via adb..."
  adb install -r "$apk_file" 2>&1 | tail -3
  if adb shell pm list packages 2>/dev/null | grep -q 'host.exp.exponent'; then
    ok "Expo Go installed on device"
  else
    err "Expo Go install did not register — check device state"
    return 1
  fi
}

# ---------- Self-smoke test: Maestro drives Settings app ----------
step_smoke() {
  [ $DO_SMOKE -eq 1 ] || return 0
  activate_path
  if ! command -v maestro >/dev/null 2>&1; then
    err "maestro not on PATH after activation"
    return 1
  fi
  local flow="$VG_MOBILE_DIR/_smoke.yaml"
  cat > "$flow" <<'EOF'
appId: com.android.settings
---
- launchApp
- takeScreenshot: vg-setup-smoke
EOF
  info "Running Maestro smoke test (launch Settings + screenshot)..."
  if maestro test "$flow" 2>&1 | tail -5 | grep -q COMPLETED; then
    ok "Maestro smoke test passed"
    local shot="$VG_MOBILE_DIR/vg-setup-smoke.png"
    if [ -f "vg-setup-smoke.png" ]; then
      mv "vg-setup-smoke.png" "$shot" 2>/dev/null
      info "  screenshot: $shot"
    fi
  else
    err "Maestro smoke test failed — see output above"
    return 1
  fi
}

# ---------- PATH hint ----------
emit_path_hint() {
  local pt="$PT_DIR"
  local mt="$MAESTRO_DIR/bin"
  local em="$SDK_DIR/emulator"
  local ct="$SDK_DIR/cmdline-tools/latest/bin"
  cat <<EOF

────────────────────────────────────────────────────────────────────
✓ Mobile environment ready. Activate for this shell:

   export ANDROID_HOME="$SDK_DIR"
   export PATH="$ct:$em:$pt:$mt:\$PATH"

To persist: append the 2 lines above to your \`~/.bashrc\` (Linux/msys),
\`~/.zshrc\` (macOS), or set as user env vars on Windows.

Boot the emulator:
   emulator -avd $VG_AVD_NAME

Verify:
   adb devices                    # expect: emulator-5554  device
   maestro --version
   python \$VGFLOW_ROOT/scripts/maestro-mcp.py --json check-prereqs
────────────────────────────────────────────────────────────────────
EOF
}

# ---------- main ----------
echo "VG mobile tooling installer (host: $HOST_OS, install root: $VG_MOBILE_DIR)"
if [ "$HOST_OS" = "unknown" ]; then
  err "Unsupported host OS. This script needs macOS, Linux, or Git Bash / MSYS on Windows."
  exit 2
fi
ensure_dir "$VG_MOBILE_DIR"

# Cleanup trap: if we launched the emulator and script exits abnormally, leave it running
# (user probably wants the emulator up for their work). Only kill on explicit interrupt.
trap_interrupt() {
  if [ -n "$EMU_PID" ] && kill -0 "$EMU_PID" 2>/dev/null; then
    warn "Interrupted — killing emulator pid $EMU_PID"
    kill "$EMU_PID" 2>/dev/null
  fi
  exit 130
}
trap trap_interrupt INT TERM

FAIL=0
step_jdk          || FAIL=1
step_adb          || FAIL=1
step_maestro      || FAIL=1
step_sdk          || FAIL=1
step_avd          || FAIL=1
step_accel_check  || true        # advisory — never fails
step_boot         || FAIL=1
step_expo_go      || FAIL=1
step_smoke        || FAIL=1

if [ $FAIL -ne 0 ]; then
  err "One or more steps failed. See output above."
  exit 1
fi
emit_path_hint

if [ $DO_BOOT -eq 1 ] && [ -n "$EMU_PID" ]; then
  echo ""
  echo "Emulator is running (pid $EMU_PID). To stop it later:"
  echo "   adb emu kill       # clean shutdown"
  echo "   kill $EMU_PID       # force"
fi
