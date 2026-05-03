# Edge Cases Template — web-fullstack profile

> AI dùng template này khi sinh `EDGE-CASES.md` cho phase profile `web-fullstack`
> hoặc `web-backend-only` (categories overlap; `web-frontend-only` dùng template
> riêng — render-focused).

## Categories (10) — chọn relevant per goal

Per goal, chọn **3-10 variants** từ categories dưới. Không bắt buộc cover all
10. Priority: critical (auth/data integrity) → high (state/concurrency) →
medium (UX edge) → low (cosmetic boundary).

### 1. Boundary inputs (data validation)

| Type | Examples |
|---|---|
| Empty / null / undefined | `name=""`, `email=null`, missing required field |
| Min/max length | `name="a"` (1 char), `name="x"*256` (max+1) |
| Numeric edges | `0`, `-1`, `Number.MAX_SAFE_INTEGER`, `NaN`, `Infinity` |
| Format violation | `email="not-an-email"`, `domain="invalid space"` |
| Encoding | `name="<script>"` (XSS), `name="O'Brien"` (SQL inj), unicode `"日本語"` |
| Type coercion | `count="5"` (string when expecting int), `active="true"` |

### 2. State transitions

| Scenario | Test |
|---|---|
| not-yet-existed | GET resource that doesn't exist → 404 |
| just-created | Read immediately after POST (race-free) |
| mid-update | PATCH while another request updating |
| deleted | GET / mutate after DELETE → 404 |
| soft-deleted-undeleted | POST same key after soft-delete → resurrect or 409? |
| state-locked | Mutate "archived" entity → 403 with "read-only" |

### 3. Auth boundaries (CRITICAL)

| Actor | Expected |
|---|---|
| Anonymous | 401 redirect to login (or 403 for API) |
| Wrong-tenant | 403 (BOLA — never leak cross-tenant data) |
| Wrong-role | 403 with role-specific error |
| Expired token | 401 with token-refresh hint |
| Revoked token | 401 with "session terminated" |
| Service-only endpoint accessed by user | 403 |

### 4. Concurrency / race

| Pattern | Test |
|---|---|
| Simultaneous create same key | 1 success + 1 conflict (409) — atomic uniqueness |
| Read-modify-write race | If-Match / version increment enforced |
| Idempotency | POST 2x same idempotency-key → same result, no double-create |
| Lock acquisition | 2 concurrent edits → 1 wins, 1 gets stale-version error |

### 5. Pagination + filter

| Edge | Test |
|---|---|
| page=0 | Either accept (1-indexed) OR reject 400 (consistent) |
| page beyond last | Empty array, NOT 404 |
| pageSize > max | Capped to max, not OOM |
| Empty result | `{items:[], total:0}` not error |
| Invalid sort field | 400 with allowlist hint |
| SQL-injection in filter | Parameterized — no command leak |

### 6. Idempotency + retry

| Pattern | Test |
|---|---|
| Network retry mid-write | Second attempt no-op via idempotency-key |
| Partial write fail | DB rollback, no orphan rows |
| Duplicate webhook delivery | Dedupe by event_id |

### 7. Time-based

| Edge | Test |
|---|---|
| Past date | start_date < now → 400 OR auto-active? |
| Future date | end_date < start_date → 400 |
| Timezone shift | Created in UTC+7, viewed in UTC-8 → display correct |
| DST transition | Schedule at 2:30 AM on DST day |
| Clock skew | Server +/- 5min vs client → token validation works? |

### 8. Resource limits

| Edge | Test |
|---|---|
| Memory cap | Upload 100MB file → reject before OOM |
| Connection pool exhausted | 50 simultaneous reqs → graceful 503 |
| Disk full | Write fail → user-facing error not 500 |
| Rate limit hit | 429 with Retry-After header |

### 9. Error propagation

| Upstream | Expected behavior |
|---|---|
| 5xx from 3rd-party API | Retry with backoff, then user-facing "service unavailable" |
| Missing dependency | Health-check fails before request reaches |
| Partial failure | Compensating transaction OR queue for retry |
| Cascading timeout | Deadline propagation, fail fast |

### 10. Data validity (semantic)

| Type | Test |
|---|---|
| Reference to deleted entity | FK constraint OR soft-delete OR ignored gracefully |
| Circular reference | Detected, returns 400 |
| Duplicate within array | Dedupe OR explicit error |
| Empty collection | Allowed OR rejected per business rule |

---

## Output format (per goal)

```markdown
# Edge Cases — G-04: User creates site with custom domain

## Boundary inputs
| variant_id | input | expected_outcome | priority |
|---|---|---|---|
| G-04-b1 | domain="" | 400 with field-level error "domain required" | critical |

## Auth boundaries
| variant_id | actor | expected_outcome | priority |
|---|---|---|---|
| G-04-a1 | anon | 401 redirect to /login | critical |
```

Variant IDs: `<goal_id>-<category_letter><N>`. Categories: b=boundary, s=state,
a=auth, c=concurrency, p=pagination, i=idempotency, t=time, r=resources,
e=error_propagation, d=data_validity.

---

## Skip when not applicable

- Read-only resource (no mutate ops) → skip categories 2, 4, 6
- Public endpoint (no auth) → skip category 3
- No persistence (compute endpoint) → skip categories 2, 5, 7, 9
- Single-instance resource → skip category 4

Document skip rationale in EDGE-CASES.md per-goal section header:
```markdown
## G-NN — <title>
**Skipped categories:** [3 — public endpoint, no auth required]
```
