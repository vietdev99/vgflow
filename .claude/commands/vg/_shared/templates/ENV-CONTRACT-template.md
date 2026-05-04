# Environment Contract — Phase {PHASE}

_Required artifact for phases with `kit:` declarations in CRUD-SURFACES.md (v2.39.0+). Closes Codex critique #6: review depends on auth/seed-data/fixtures/runtime-state — workers produce false confidence if env is partial._

```yaml
schema_version: "1"
phase: "{PHASE}"
generated_at: "{ISO}"

# Where the running app is reachable for review workers.
target:
  base_url: "http://localhost:3001"   # required — empty = abort review
  health_endpoint: "/api/health"      # used for pre-flight reachability check
  expected_health_status: 200

# Test users seeded in DB. Must match what review-fixture-bootstrap.py
# logs in as. Roles here drive worker spawn matrix.
seed_users:
  admin:
    email: "admin@test.local"
    user_id: "u-admin-001"            # known stable ID for cross-resource auth tests
    tenant_id: "t-test-001"
  user:
    email: "user@test.local"
    user_id: "u-user-001"
    tenant_id: "t-test-001"
  user_other_tenant:
    email: "user2@test.local"
    user_id: "u-user-002"
    tenant_id: "t-test-002"           # for tenant-leakage tests

# Fixtures expected to exist before review starts.
seed_data:
  - resource: "topup_requests"
    count_min: 5
    must_include_states: ["pending", "approved"]
  - resource: "users"
    count_min: 2
    must_include_owners: ["u-admin-001", "u-user-001"]

# Feature flags expected ON during review. If app uses LaunchDarkly /
# GrowthBook / config flags, declare expected state.
feature_flags:
  - name: "topup_v2_ui"
    expected: true
    rationale: "review tests new UI; old UI still wired but expected hidden"
  - name: "experimental_bulk_archive"
    expected: false

# Third-party stubs/mocks. If review hits real Stripe/SendGrid/etc by
# accident → false-confidence. Declare which integrations are stubbed.
third_party_stubs:
  - service: "stripe"
    mode: "stubbed"                   # stubbed | live | not_used
    stub_endpoint: "http://localhost:3001/__stub/stripe"
  - service: "sendgrid"
    mode: "stubbed"
    captured_at: ".vg/.email-capture/"
  - service: "s3"
    mode: "live-test-bucket"          # acceptable for upload tests if isolated bucket
    bucket: "test-uploads-vgreview"

# Runtime state expected. Migrations, search indexes, queues.
runtime_state:
  migrations_applied: "all"           # all | up_to_<commit> | manual_check_required
  search_indexes:
    - name: "topup_requests"
      expected_doc_count_min: 5
  message_queues:
    - name: "audit_log_consumer"
      mode: "stubbed"                 # stubbed = capture but don't process

# Pre-flight verification. review-env-preflight.py runs these before
# spawning any worker. Each check has a probe + expected outcome.
preflight_checks:
  - name: "app_reachable"
    probe: "GET ${target.base_url}${target.health_endpoint}"
    expect: "${target.expected_health_status}"
  - name: "admin_login_works"
    probe: "POST ${target.base_url}/api/auth/login {email: admin}"
    expect: "200 with token"
  - name: "seed_topup_requests_exist"
    probe: "GET ${target.base_url}/api/topup-requests as admin"
    expect: "row_count >= 5"

# Out-of-scope: what review explicitly does NOT cover. Prevents
# false-positive findings on intentionally-excluded surface.
out_of_scope:
  - "/internal/admin-tools/*"          # operations team only
  - "third-party SSO callbacks"
  - "scheduled cleanup jobs (dev env disables cron)"
```

## Why this artifact exists

Codex review v2.38: *"VG depends on auth, seeded data, build URL, fixtures, and runtime state. If PrintwayV3 has partial data, stale migrations, missing feature flags, or third-party callbacks disabled, workers will produce false confidence."*

Without ENV-CONTRACT.md, review can `PASS` because:
- Workers tested empty list views (no seed data → empty state always renders)
- Auth tokens valid but for wrong tenant
- Mutations succeeded but third-party callback live-fired into prod email
- Feature flag changes silently invalidate test paths

ENV-CONTRACT is a **read-by-workers** declaration. Workers verify their assumptions against this contract before reporting findings. If env doesn't match contract → review aborts pre-spawn (exit 2 with concrete "fix env or update contract" message).

## Override path

Pass `--skip-env-contract="<reason>"` to review CLI. Logs OVERRIDE-DEBT critical entry. Reviewer must triage at `/vg:accept`.

For phases without UI (backend-only, library, CLI), kit is `static-sast` and ENV-CONTRACT is OPTIONAL — only `target.code_root` (path to source root) needed.
