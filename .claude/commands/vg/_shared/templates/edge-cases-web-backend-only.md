# Edge Cases Template — web-backend-only profile

> Backend API endpoints, no FE in scope. Subset của `web-fullstack` template
> nhưng skip render/UI categories.

## Categories (8) — chọn relevant per goal

Use full list từ `edge-cases-web-fullstack.md` categories 1-10, NHƯNG SKIP:
- Category 5 partial (pagination UI parts) — keep API edges only
- No render/UX testing — backend phase

Effective categories (8):
1. **Boundary inputs** — full
2. **State transitions** — full
3. **Auth boundaries** — full (CRITICAL — backend is auth boundary)
4. **Concurrency / race** — full
5. **Pagination + filter** — API edges only (page=0, beyond-last, sort allowlist, etc)
6. **Idempotency + retry** — full
7. **Time-based** — full
8. **Resource limits** — full
9. **Error propagation** — full (CRITICAL — backend handles upstream failures)
10. **Data validity** — full

Refer to `edge-cases-web-fullstack.md` cho mô tả chi tiết per category.

---

## Output format (per goal)

Identical to web-fullstack output format. Just don't include FE-only
categories (render variants, modal lifecycle, etc).

---

## Backend-specific emphasis

For BE-only phases, prioritize:
- **Category 3 (Auth)** — every endpoint must test anon/wrong-tenant/wrong-role
- **Category 4 (Concurrency)** — DB-level guarantees (uniqueness, FK)
- **Category 6 (Idempotency)** — webhook receivers, payment endpoints
- **Category 9 (Error propagation)** — distributed system resilience

Skip patterns (acceptable to omit):
- Read-only public endpoint → skip 3, 6
- Simple cache-fronted GET → skip 4
- No upstream deps → skip 9
