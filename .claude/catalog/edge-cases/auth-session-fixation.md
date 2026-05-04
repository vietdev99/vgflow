---
id: auth-session-fixation
surface: api
tags: [auth, security, session]
severity: critical
---

**Pattern:** Login does not rotate session cookie. Attacker pre-plants
an empty cookie, victim logs in, attacker reuses the now-authenticated
cookie.

**Failure mode:**
- Attacker visits site, gets `sess_id=ATK`.
- Lures victim to a URL that drops `sess_id=ATK` cookie (e.g., open
  redirect, subdomain XSS, stored cookie injection via header reflection).
- Victim logs in; backend marks `sess_id=ATK` as authenticated.
- Attacker hits app with same cookie → full account access.

**Edge cases test must cover:**
- POST /login response MUST contain `Set-Cookie: sess_id=NEW; ...`
  with a different value than any cookie sent in the request.
- Logout MUST invalidate the cookie server-side (cookie list table or
  signed token revocation).
- Cookie attributes: `HttpOnly; Secure; SameSite=Strict|Lax`.
- Session ID entropy ≥ 128 bits.

**OWASP reference:** A07:2021 — Identification and Authentication Failures.
