---
id: concurrent-mutation-race
surface: api
tags: [race, concurrency, integrity]
severity: high
---

**Pattern:** Two clients update the same resource concurrently; the
second write overwrites the first without either party noticing.

**Failure mode:**
- Client A: GET resource (v=1, balance=100). Client B: GET (v=1, 100).
- Client A: PUT balance=150 (forgot to apply +50 from a prior tx).
- Client B: PUT balance=180.
- Final balance = 180; A's intent lost ("lost-update").

**Edge cases test must cover:**
- Optimistic concurrency: send `If-Match: <etag>` on PUT; server
  returns 412 Precondition Failed when version mismatches.
- Test with deliberately stale ETag → must get 412.
- Server-side row-level lock for critical mutations (DB SELECT FOR UPDATE).
- Distributed lock (Redis SETNX, etcd, Postgres advisory lock) for
  mutations that span multiple rows.
- Idempotency-Key on PUT/PATCH (RFC 7240).

**Reference:** Lost-update problem — Atkinson & Buneman, 1987.
