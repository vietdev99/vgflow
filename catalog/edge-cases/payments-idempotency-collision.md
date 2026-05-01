---
id: payments-idempotency-collision
surface: api
tags: [payments, idempotency, retry, money_like]
severity: high
---

**Pattern:** Same `Idempotency-Key` with different body returns cached
response, not a 4xx. Silent data corruption when caller retries with
drift.

**Failure mode:**
- Caller A POST `{amt: 100, key: K}` → 201 receipt R.
- Caller B POST `{amt: 200, key: K}` → 200 returns R (cached).
- B never billed; reconciliation diverges between client and server.

**Edge cases test must cover:**
- Same key, identical body → second response = first (expected).
- Same key, different body → MUST return 422 or 409, NOT a stale 200.
- Same key, partial body change (e.g., metadata) → policy decision
  must be documented and tested.
- Key collision across users (multi-tenant) → MUST scope to
  user/tenant; cross-tenant key reuse is a data leak risk.

**RFC reference:** RFC 7240 §4.3 (Idempotency-Key header).
