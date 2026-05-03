---
id: ui-double-submit
surface: ui
tags: [ui, idempotency, race]
severity: medium
---

**Pattern:** User clicks Submit twice (impatient, slow network, double-tap
on mobile). Without front-end disable + back-end idempotency, two POSTs
fire — money double-charged or two records created.

**Failure mode:**
- Click 1: POST /api/topup, button stays clickable while in-flight.
- Click 2 (200ms later): second POST.
- Server processes both → 2 receipts.

**Edge cases test must cover:**
- Submit button MUST disable on click; re-enable on response.
- Loading spinner shown during in-flight request.
- Server idempotency: same Idempotency-Key returns cached response
  (see `payments-idempotency-collision`).
- Optimistic UI: temporarily show "submitting..." with rollback on error.
- Mobile: double-tap zoom disabled on the button to avoid 2 events.

**Reference:** Cause of P3.D-12 dogfood incident (PrintwayV3 v3.2 topup).
