# TEST-GOAL enriched template (v2.2+)

Optional frontmatter fields for each goal in `TEST-GOALS.md`. Backward-
compatible: legacy goals without these fields still work. Blueprint step
2b5 should emit enriched format; consumers (review/test/accept) read when
present, gracefully degrade when absent.

## Schema

```yaml
---
id: G-XX
title: "Short user-observable behavior"
priority: critical | important | nice
surface: ui | api | data | integration | time-driven | custom

# v2.2 enrichment (all optional but recommended)
actor: <role + authentication state>
  # e.g. "publisher (role=publisher, authenticated)"
  #      "anonymous (unauthenticated visitor)"
  #      "cron (system, runs 0 */5 * * *)"

precondition:
  # List of system state required before goal can trigger
  - <imported_goal_or_UC_id>  # e.g. UC-GEN-AUTH-01 (logged in)
  - <explicit state>          # e.g. "has_verified_site"
  - <data requirement>        # e.g. "quota_available"

trigger: <user-observable action or event>
  # e.g. "Click 'Create Ad Unit' button"
  #      "POST /api/sites/{id}/ad-units from client"
  #      "Kafka message on topic bid-requests"

main_steps:
  # Ordered list of user-visible OR system actions. Each step = 1 observable.
  - S1: <action>              # e.g. "Open form modal"
  - S2: <action>              # e.g. "Fill name + size + type"
  - S3: <action>              # e.g. "Submit form"
  - S4: <action>              # e.g. "API validates + persists"
  - S5: <action>              # e.g. "List refresh with new entry"

alternate_flows:
  # Named failure modes + expected system behavior
  - name: <short_id>
    trigger: <what causes alternate flow>
    expected: <observable outcome>
  # e.g.
  # - name: validation_fail
  #   trigger: missing required field
  #   expected: inline errors shown, stay on modal
  # - name: quota_exceeded
  #   trigger: user at/above site quota
  #   expected: upgrade prompt shown, submission blocked

postcondition:
  # State after successful main_flow execution. MUST include side effects.
  - <db state change>         # e.g. "ad_unit row inserted with status=pending_review"
  - <event emission>          # e.g. "event 'ad_unit_created' emitted to Kafka"
  - <cache invalidation>      # e.g. "sites_list cache for publisher invalidated"
  - <ui state>                # e.g. "list UI shows new item at top"

# Verification binding (existing v1.14 fields)
verification: automated | manual | deferred | skipped
tests: [TS-XX, TS-YY]         # bind to test files via TS-XX markers

# Evidence fields (populated by /vg:test, /vg:review)
status: NOT_SCANNED | READY | BLOCKED | UNREACHABLE | FAILED | DEFERRED | INFRA_PENDING | MANUAL
evidence_file: apps/web/e2e/xxx.spec.ts:42 | apps/api/test/xxx.test.ts
---

## Prose description (optional)

Narrative context for humans reviewing goal. Not parsed by validators.
```

## Example — real goal (phase 14 G-01)

```yaml
---
id: G-01
title: "Publisher login respects domain-role fit"
priority: critical
surface: api + ui
actor: publisher (role=publisher, unauthenticated before login)
precondition:
  - has_verified_account
  - domain_route_configured (ssp.vollx.com → publisher app)
trigger: "POST /api/v1/auth/login from ssp.vollx.com origin"
main_steps:
  - S1: Client POST credentials + domain header to /api/v1/auth/login
  - S2: API validates domain-role fit via AuthDomain enum
  - S3: API issues JWT with domain=ssp claim + refresh cookie scoped to ssp domain
  - S4: Client redirected to publisher dashboard
  - S5: Subsequent requests include JWT — middleware validates JWT.domain matches Origin header
alternate_flows:
  - name: domain_role_mismatch
    trigger: admin account attempts login from ssp.vollx.com
    expected: 403 with VG_ERR_DOMAIN_ROLE_UNFIT + Vietnamese toast "Tài khoản không có quyền cho domain này"
  - name: invalid_origin
    trigger: request from unapproved domain (e.g. evil.com)
    expected: 403 via CORS preflight + VG_ERR_DOMAIN_ORIGIN_INVALID logged
postcondition:
  - jwt_issued with domain=ssp in payload
  - refresh_cookie set with Domain=.ssp.vollx.com Path=/api/v1/auth
  - session row in Redis with key "session:ssp:{user_id}:{device_id}"
  - event "auth.login" emitted with {domain, user_id, success: true}
verification: automated
tests: [TS-01, TS-02]
status: READY
evidence_file: apps/web/e2e/auth-domain-isolation.spec.ts:23
---

Publisher can only log in from their designated SSP domain. Cross-domain
attempts (admin credentials on SSP domain) are rejected with clear error
message in Vietnamese. Session cookies scoped to domain prevent cross-
site token leak.
```

## Migration

- **Existing goals** (v1.14 format): no action needed. Missing fields = validators skip enrichment checks.
- **New phases** (scope/blueprint v2+): blueprint step 2b5 SHOULD emit enriched format. AI reads this template to infer structure.
- **Manual enrichment**: user edits TEST-GOALS.md adding fields. Validators re-run, may unlock additional coverage.

## Consumer behavior

| Command | Reads enriched fields | Effect |
|---------|----------------------|--------|
| `/vg:blueprint` step 2b5 | Generates via AI prompt | AI pattern-matches template → uses enriched format |
| `/vg:build` executor | Reads `precondition` + `alternate_flows` | Task context includes error handling requirements |
| `/vg:review` goal comparison | Reads `main_steps` + `postcondition` | Maps to RUNTIME-MAP observed sequences |
| `/vg:test` codegen | Reads all enriched fields | Generates Playwright scenarios per `alternate_flows` names |
| `/vg:accept` UAT checklist | Reads `actor` + `postcondition` | User UAT items phrased in enriched language |

Each consumer's enrichment is **additive** — absence of field = legacy path.
