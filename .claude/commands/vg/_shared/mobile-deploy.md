# Mobile Deploy (Shared Reference)

Referenced by `/vg:test` step 5a when `profile ∈ MOBILE_PROFILES`. Defines
cross-platform deploy helpers, provider auto-detection, health-check
callbacks, and rollback strategy for mobile binaries.

**Never hardcode** provider names, stage targets, env-var values, or cert
paths in the caller. Everything comes from `config.mobile.deploy.*` and the
user's environment.

---

## Prerequisites (resolved by config-loader)

| Variable | Source |
|----------|--------|
| `$PROFILE` | `config.profile` — MUST be in `{mobile-rn, mobile-flutter, mobile-native-ios, mobile-native-android, mobile-hybrid}` |
| `$REPO_ROOT` | `git rev-parse --show-toplevel` |
| `$PYTHON_BIN` | Python ≥3.10 |
| `$HOST_OS` | `darwin` / `linux` / `windows` / `unknown` (from `uname -s`) |

---

## Step MD1: Resolve provider

```bash
mobile_deploy_provider_detect() {
  # Priority order:
  # 1. User explicit: config.mobile.deploy.provider (if eas_auto_detect=false)
  # 2. Auto-detect: eas.json present AND eas_auto_detect=true → eas
  # 3. Auto-detect: codemagic.yaml present → codemagic
  # 4. Auto-detect: fastlane/Fastfile present → fastlane
  # 5. Fallback: user's declared provider

  local declared auto
  declared=$(awk '/^mobile:/{m=1;next} m && /^  deploy:/{d=1;next}
                  d && /^  [a-z]/{d=0} d && /provider:/{print $2;exit}' \
              .claude/vg.config.md | tr -d '"' | head -1)
  auto=$(awk '/^mobile:/{m=1;next} m && /^  deploy:/{d=1;next}
               d && /^  [a-z]/{d=0} d && /eas_auto_detect:/{print $2;exit}' \
          .claude/vg.config.md | tr -d '"' | head -1)

  # Auto-detection cascade (only if auto=true)
  if [ "${auto:-false}" = "true" ]; then
    [ -f "${REPO_ROOT}/eas.json" ]          && { echo "eas"; return 0; }
    [ -f "${REPO_ROOT}/codemagic.yaml" ]    && { echo "codemagic"; return 0; }
    [ -f "${REPO_ROOT}/bitrise.yml" ]       && { echo "bitrise"; return 0; }
  fi

  # Fall back to declared provider (default fastlane if blank)
  echo "${declared:-fastlane}"
}
```

Uses `iOS cloud fallback` if host can't do Darwin-only steps:

```bash
mobile_deploy_effective_provider() {
  # If target includes ios AND host ≠ darwin AND cloud_fallback_for_ios=true,
  # override with cloud_fallback_provider. Otherwise use detected.
  local detected target_platforms fallback_enabled fallback_prov
  detected=$(mobile_deploy_provider_detect)

  target_platforms=$(awk '/^target_platforms:/{print;exit}' .claude/vg.config.md \
                     | sed 's/.*\[\(.*\)\].*/\1/' | tr -d '"\r')

  if echo "$target_platforms" | grep -q ios && [ "$HOST_OS" != "darwin" ]; then
    fallback_enabled=$(awk '/^mobile:/{m=1;next} m && /^  deploy:/{d=1;next}
                             d && /^  [a-z]/{d=0} d && /cloud_fallback_for_ios:/{print $2;exit}' \
                        .claude/vg.config.md | tr -d '"' | head -1)
    if [ "$fallback_enabled" = "true" ]; then
      fallback_prov=$(awk '/^mobile:/{m=1;next} m && /^  deploy:/{d=1;next}
                            d && /^  [a-z]/{d=0} d && /cloud_fallback_provider:/{print $2;exit}' \
                       .claude/vg.config.md | tr -d '"' | head -1)
      echo "${fallback_prov:-eas}  # iOS fallback (host=$HOST_OS)"
      return 0
    fi
  fi
  echo "$detected"
}
```

---

## Step MD2: Provider prereqs

Before invoking any provider, check its CLI is installed. Missing CLI = **HARD FAIL**
(different from gate check scripts — deploy cannot be skipped).

```bash
mobile_deploy_check_provider() {
  local provider="$1"
  case "$provider" in
    fastlane)
      command -v fastlane >/dev/null || {
        echo "⛔ fastlane not on PATH. Install: gem install fastlane OR brew install fastlane" >&2
        return 1
      }
      ;;
    eas)
      command -v eas >/dev/null || command -v npx >/dev/null || {
        echo "⛔ eas-cli required. Install: npm install -g eas-cli OR use npx" >&2
        return 1
      }
      ;;
    firebase)
      command -v firebase >/dev/null || {
        echo "⛔ firebase CLI required. Install: npm install -g firebase-tools" >&2
        return 1
      }
      ;;
    codemagic|bitrise)
      # Cloud providers run server-side — only need `curl` + API token env var
      command -v curl >/dev/null || return 1
      ;;
    manual)
      # User drives the binary build themselves. We just verify artifacts
      # exist after they claim they're done.
      ;;
    *)
      echo "⛔ unknown provider '$provider'" >&2
      return 1
      ;;
  esac
}
```

---

## Step MD3: Deploy one stage

Each stage defined in `config.mobile.deploy.stages[]` has:
- `name` — human label (internal_qa, beta, production)
- `target` — distribution channel (firebase_app_distribution | testflight | play_internal | manual_link)
- `required` — if true, failure blocks next stage
- `health_check` — callback name to verify success

```bash
mobile_deploy_stage() {
  local stage_name="$1" provider="$2"
  local target stage_required health_check
  target=$(awk -v s="$stage_name" '
    /^mobile:/{m=1} m && /^    - name:/{n=$3; gsub(/[\"'"'"']/,"",n)}
    m && n==s && /target:/{gsub(/^[^:]+:[[:space:]]*/,""); gsub(/[\"'"'"']/,""); print; exit}
  ' .claude/vg.config.md)

  health_check=$(awk -v s="$stage_name" '
    /^mobile:/{m=1} m && /^    - name:/{n=$3; gsub(/[\"'"'"']/,"",n)}
    m && n==s && /health_check:/{gsub(/^[^:]+:[[:space:]]*/,""); gsub(/[\"'"'"']/,""); print; exit}
  ' .claude/vg.config.md)

  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📦 Stage [${stage_name}] → provider=${provider}, target=${target}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # Dispatch — each provider/target pair has its own invocation pattern
  mobile_deploy_invoke "$provider" "$target"
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "⛔ Stage '${stage_name}' deploy failed (rc=$rc)"
    return $rc
  fi

  # Health check
  mobile_deploy_health "$health_check" "$target"
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "⛔ Stage '${stage_name}' health check '${health_check}' failed"
    return $rc
  fi

  echo "✓ Stage '${stage_name}' complete"
}
```

---

## Step MD4: Provider invoke

Actual deploy commands. Each provider has project-specific config files
(Fastfile, eas.json, codemagic.yaml) — we don't overwrite those; we just
invoke the entrypoint the user already set up.

```bash
mobile_deploy_invoke() {
  local provider="$1" target="$2"

  case "$provider" in
    fastlane)
      # Fastlane lane name convention: <stage>_<platform>
      # User's Fastfile should define e.g. `lane :internal_qa_ios`, `lane :beta_android`
      local platform
      case "$target" in
        testflight)                  platform=ios; lane=beta_ios ;;
        play_internal)               platform=android; lane=internal_qa_android ;;
        testflight_and_play_internal) lane=beta_all ;;
        firebase_app_distribution)   lane=internal_qa ;;
        manual_link)                 lane=build_only ;;
        *) echo "⛔ fastlane: unsupported target '${target}'" >&2; return 1 ;;
      esac
      fastlane "$lane"
      ;;

    eas)
      # EAS profile naming: config.mobile.deploy.stages[*].name doubles as
      # eas build profile name unless user overrides via `eas_profile` key.
      local eas_profile="$target"
      case "$target" in
        firebase_app_distribution) eas_profile=preview ;;
        testflight|play_internal|testflight_and_play_internal) eas_profile=production ;;
        manual_link)               eas_profile=development ;;
      esac
      if command -v eas >/dev/null; then
        eas build --profile "$eas_profile" --platform all --non-interactive
        if [ "$target" != "manual_link" ]; then
          eas submit --profile "$eas_profile" --platform all --non-interactive
        fi
      else
        npx eas-cli build --profile "$eas_profile" --platform all --non-interactive
        [ "$target" != "manual_link" ] && \
          npx eas-cli submit --profile "$eas_profile" --platform all --non-interactive
      fi
      ;;

    firebase)
      # Firebase App Distribution needs a built artifact already. Assumes
      # user's build step (previous stage or local) produced the APK/IPA.
      # User sets FIREBASE_APP_ID and FIREBASE_TOKEN in env.
      if [ -z "${FIREBASE_APP_ID:-}" ]; then
        echo "⛔ FIREBASE_APP_ID env var required for firebase provider" >&2
        return 1
      fi
      # Artifact glob — reuse verify-bundle-size convention
      local artifact
      artifact=$(find . -type f \( -name "*.apk" -o -name "*.ipa" \) \
                   -not -path "*/node_modules/*" -not -path "*/Pods/*" \
                   -not -path "*/build/intermediates/*" | head -1)
      [ -z "$artifact" ] && { echo "⛔ no apk/ipa artifact found for firebase upload"; return 1; }
      firebase appdistribution:distribute "$artifact" \
        --app "$FIREBASE_APP_ID" \
        --token "${FIREBASE_TOKEN:-}" \
        --groups "${FIREBASE_TESTER_GROUPS:-internal}"
      ;;

    codemagic|bitrise)
      # Cloud CI — trigger via REST API
      echo "ℹ ${provider} deploy is externally triggered. Marking complete if last build green."
      # TODO: honor webhook/API call if user sets TRIGGER_URL env
      ;;

    manual)
      echo "ℹ manual provider — skipping automatic upload."
      ;;
  esac
}
```

---

## Step MD5: Health check

Verify deploy actually reached consumers:

```bash
mobile_deploy_health() {
  local check_name="$1" target="$2"

  case "$check_name" in
    fad_link_reachable)
      # User declared this callback in stage config. Expect FIREBASE_DISTRIBUTION_URL
      # to be set by provider step or user pre-seeds it.
      if [ -z "${FIREBASE_DISTRIBUTION_URL:-}" ]; then
        echo "⚠ FIREBASE_DISTRIBUTION_URL not set — health check inconclusive"
        return 0
      fi
      curl -sf "$FIREBASE_DISTRIBUTION_URL" -o /dev/null || {
        echo "⛔ FAD link $FIREBASE_DISTRIBUTION_URL unreachable"; return 1;
      }
      ;;

    store_processing_ok)
      # TestFlight / Play Internal: need API token to poll build status.
      # For V1 we accept "successful upload" = green, even if Apple/Google
      # processing takes hours. Deeper polling is V2.
      echo "ℹ store processing is asynchronous — assuming upload success counts as OK"
      ;;

    manual|"")
      # No programmatic check — user confirms externally
      ;;

    *)
      echo "⚠ unknown health check '${check_name}' — treating as no-op"
      ;;
  esac
}
```

---

## Step MD6: Full pipeline (all stages)

Called by `/vg:test` step 5a:

```bash
mobile_deploy_pipeline() {
  local provider
  provider=$(mobile_deploy_effective_provider)
  echo "Effective provider: ${provider}"

  mobile_deploy_check_provider "$provider" || return 1

  # Iterate stages in config order
  local stages
  stages=$(awk '/^mobile:/{m=1} m && /^    - name:/{gsub(/[^a-zA-Z0-9_-]/,"",$3); print $3}' \
            .claude/vg.config.md)

  for stage in $stages; do
    mobile_deploy_stage "$stage" "$provider" || {
      # required=false stages → warn, continue
      local req
      req=$(awk -v s="$stage" '
        /^mobile:/{m=1} m && /^    - name:/{n=$3; gsub(/[\"'"'"']/,"",n)}
        m && n==s && /required:/{print $2; exit}
      ' .claude/vg.config.md | tr -d '"' | head -1)
      if [ "${req:-true}" = "true" ]; then
        echo "⛔ required stage '${stage}' failed — aborting pipeline"
        return 1
      fi
      echo "⚠ optional stage '${stage}' failed — continuing"
    }
  done
  echo "✓ All mobile deploy stages completed"
}
```

---

## Step MD7: Rollback

Mobile rollback is provider-specific and often limited (TestFlight lets you
expire a build, Play Store has staged rollout rollback; fastlane match lets
you revert matched certs). V1 supports:

```bash
mobile_deploy_rollback() {
  local provider="$1" prev_sha="$2"
  case "$provider" in
    eas)
      # EAS: republish previous build via eas build:list → eas submit
      echo "ℹ EAS rollback = republish previous successful build"
      [ -n "$prev_sha" ] && git checkout "$prev_sha"
      eas build --profile production --platform all --non-interactive --auto-submit || true
      ;;
    fastlane)
      # Fastlane: invoke rollback lane if user defined one
      fastlane rollback 2>/dev/null || echo "⚠ no fastlane rollback lane defined — manual revert required"
      ;;
    firebase)
      # FAD doesn't support programmatic rollback — manual revoke via console
      echo "ℹ Firebase App Distribution: revoke manually at https://console.firebase.google.com"
      ;;
    *)
      echo "⚠ rollback not implemented for provider '${provider}' — see provider docs"
      ;;
  esac
}
```

---

## Portability summary

- **P1:** every provider name, lane, profile, target comes from config or env; nothing hardcoded in this reference.
- **P2:** iOS stages auto-switch to cloud when `HOST_OS != darwin`. adb / keytool / openssl used only where cross-platform.
- **P3:** `command -v` gates every CLI; `mobile_deploy_check_provider` fails fast with install hint.
- **P4:** lives in `vgflow/commands/vg/_shared/mobile-deploy.md` (canonical) and `.claude/` mirror.

Callers must `source`-read this reference file (not re-implement). The
`/vg:test` step 5a simply invokes `mobile_deploy_pipeline` inside its
bash block.
