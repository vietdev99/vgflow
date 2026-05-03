# Edge Cases Template — web-frontend-only profile

> Render-focused edge cases for FE-only phases. Cho phase web-fullstack có UI,
> dùng template này KÈM `edge-cases-web-fullstack.md` (BE+FE đều cover).

## Categories (8) — chọn relevant per goal

### 1. Render variants (data shape)

| Type | Test |
|---|---|
| Empty list | "Chưa có item nào" empty state (text + CTA), không phải spinner mãi |
| 1 item | Render OK, không lệch layout |
| Many items (overflow) | Virtual scroll OR pagination, không freeze |
| Very long text | Truncate với "..." OR wrap, không break layout |
| Missing optional fields | Fallback hiển thị "—" hoặc skip, không "undefined" |
| Mixed types in array | All variants render OK |

### 2. State persistence

| Edge | Test |
|---|---|
| localStorage empty | Default state load OK |
| localStorage corrupted | Detected (try/catch), reset không crash |
| localStorage quota full | Graceful — fallback to in-memory |
| Cookie expired mid-session | Re-login prompt, không silent fail |
| Session restored | Form draft restore, scroll position kept |

### 3. Network resilience

| Scenario | Expected UX |
|---|---|
| Offline | Show offline banner, disable submit |
| Slow (3G) | Loading indicator >500ms, không freeze input |
| Flaky (50% drop) | Retry với exponential backoff, không spam |
| Timeout | "Mất kết nối — thử lại?" với retry button |
| 5xx response | "Server đang gặp sự cố" (NOT raw error code) |
| Concurrent fetches cancel | AbortController hủy stale request |

### 4. Browser quirks

| Browser | Edge case |
|---|---|
| Safari | localStorage cap, Date parsing, IndexedDB limits |
| Firefox | CSS grid quirks, scrollbar width |
| iOS Safari | Viewport units (vh), scroll bounce, touch events |
| Mobile Chrome | Pull-to-refresh conflict |
| IE / legacy | Either polyfill OR explicit "browser unsupported" page |

### 5. Input UX

| Edge | Test |
|---|---|
| Paste large content | Truncate OR show paste-too-large error |
| IME composition (VN/JP/CN) | Don't fire onChange mid-composition |
| Clipboard formats | text/html parsed safely (XSS prevention) |
| Auto-fill | Browser autofill works, password manager compatible |
| Mobile keyboard | Doesn't cover input field (scrollIntoView) |
| Copy/paste timestamp | Format-flex parser |

### 6. Modal lifecycle

| State | Test |
|---|---|
| Opened from another modal | Stack OR replace per design system |
| ESC dismiss | Close + return focus to opener |
| Click outside | Configurable (form modal: confirm; info modal: dismiss) |
| Reopen idempotent | State reset, no leak |
| Focus trap | Tab cycles within modal |
| Body scroll lock | While open, body doesn't scroll |

### 7. Form lifecycle

| State | Test |
|---|---|
| Pre-filled (edit mode) | All values populate correctly |
| Partially filled | Save draft OR warn on unsaved change |
| Submit during validation | Disable submit while validating |
| Submit while submitting | Idempotency — disable button + show spinner |
| Submit on Enter | Enter triggers submit only when last field |
| Field-level error | Show inline, scroll to first error |
| Multi-step form | Back/forward preserves data |

### 8. Sub-component robustness

| Edge | Test |
|---|---|
| Lazy load fail | Suspense fallback shows error boundary |
| Image broken | Alt text + fallback icon |
| Iframe blocked | "Content unavailable" message |
| Web component not registered | Graceful degradation |
| Third-party widget down | Don't block parent render |

---

## Output format (per goal)

```markdown
# Edge Cases — G-12: Campaign list view

## Render variants
| variant_id | input_data | expected_render | priority |
|---|---|---|---|
| G-12-r1 | empty list | empty state text + "Tạo campaign" CTA | critical |
| G-12-r2 | 1 item | row renders, không lệch | high |
| G-12-r3 | 1000 items | virtual scroll, no freeze | high |

## Network resilience
| variant_id | scenario | expected_ux | priority |
|---|---|---|---|
| G-12-n1 | offline | offline banner + disabled submit | critical |
```

Variant IDs: `<goal_id>-<category_letter><N>`. Categories: r=render, s=state,
n=network, b=browser, i=input, m=modal, f=form, c=component.

---

## Skip when not applicable

- No persisted state → skip 2
- Always-online assumption (internal tool) → skip 3
- Desktop-only → skip 6 mobile parts
- Read-only display → skip 7
- No third-party widgets → skip 8

Document skip in section header.
