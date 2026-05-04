# Edge Cases Template — mobile-* profile

> For mobile-react-native, mobile-flutter, mobile-native phases. Categories
> mobile-specific (permissions, lifecycle, network handoff). Pair with
> `edge-cases-web-frontend-only.md` cho UI render variants chung.

## Categories (5) — chọn relevant per goal

### 1. Permissions

| Type | Test |
|---|---|
| Granted | Feature works as designed |
| Denied (first time) | Show value-prop screen, retry option |
| Denied (permanent) | Deep-link to system Settings, OR feature gracefully degrades |
| Restricted (kid mode / MDM) | Show "blocked by admin" message |
| Limited (iOS 14+ photos) | Use only granted subset |
| Conditional (foreground only) | Test transitions to background |

Common permissions: camera, photos/media, location (precise/approximate),
microphone, contacts, push notifications, biometrics, calendar.

### 2. Background / foreground / lifecycle

| State | Test |
|---|---|
| App suspended mid-action | Resume completes (or graceful "session expired") |
| Push notification taps when killed | Cold-start to deep-linked screen |
| Force-quit + reopen | State restored OR fresh start (consistent) |
| Memory pressure (OS kills) | Restore from saved state on relaunch |
| Phone call interruption | Audio/video pauses, resume after |
| Background fetch | Quota respected, doesn't drain battery |
| App update mid-run | New version reload prompt |

### 3. Network state

| Scenario | Test |
|---|---|
| Cellular only | Configurable: cellular allowed/blocked per data type |
| WiFi → cellular handoff | Mid-upload doesn't fail (resumable) |
| Airplane mode | Offline banner, queued mutations sync on return |
| Captive portal (hotel WiFi) | Detect 200 with redirect, prompt browser |
| VPN | Latency tolerated, retry policy works |
| IPv6-only | DNS resolves OK, no IPv4 hardcoding |
| Carrier proxy | TLS pinning doesn't break (or fallback) |

### 4. Device state

| Edge | Test |
|---|---|
| Low storage (<100MB) | Cache eviction, downloads warn or queue |
| Low memory (<5%) | Lite mode OR reject heavy operation |
| Low battery (<20%) | Defer non-critical bg work |
| Battery saver mode | Reduce animations, sync less |
| Dark mode | All text/images readable |
| High contrast / reduce motion | Honored per OS API |
| Charging vs not | Background sync more aggressive when charging |
| Different DPI / screen size | Layout adapts (foldable, tablet, small phone) |
| Rotation | State preserved on portrait↔landscape |

### 5. Notification surfaces

| Surface | Test |
|---|---|
| In-app banner | Doesn't block CTA, dismissible |
| Push (foreground) | Sound + banner per user preference |
| Push (background) | System notification fires, deep-link works |
| Lock screen | Sensitive data hidden (privacy mode) |
| Notification center | Stacked correctly, badges count match |
| Action buttons | Reply/dismiss work without unlocking |
| Silent push (data-only) | Wakes app, no UI |
| Critical alert (iOS) | Bypasses DnD only if entitled |

---

## Output format (per goal)

```markdown
# Edge Cases — G-22: User uploads receipt photo

## Permissions
| variant_id | actor_state | expected_outcome | priority |
|---|---|---|---|
| G-22-p1 | photos: denied first time | value-prop screen + retry CTA | critical |
| G-22-p2 | photos: limited (iOS 14+) | use only selected subset, no error | high |

## Network state
| variant_id | scenario | expected_outcome | priority |
|---|---|---|---|
| G-22-n1 | airplane mode | queue upload, offline banner | critical |
| G-22-n2 | wifi→cellular mid-upload | resume from chunk N | high |
```

Variant IDs: `<goal_id>-<category_letter><N>`. Categories: p=permission,
l=lifecycle, n=network, d=device, x=notification.

---

## Skip when not applicable

- Pure-display feature (no data input) → skip 1
- Fully online-required → skip 3 partial
- No notifications → skip 5

Document skip in section header.

---

## Cross-platform parity check

Cuối EDGE-CASES.md cho mobile phase, thêm matrix:

| Variant | iOS native | Android native | Cross-platform (Flutter/RN) |
|---|---|---|---|
| G-22-p1 | ✅ | ✅ | ✅ — same UX |
| G-22-d3 (battery saver) | iOS Low Power Mode API | Android battery saver intent | ⚠️ RN bridge needed |

Variants có behavior khác giữa platforms phải document trong cell.
