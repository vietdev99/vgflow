---
id: upload-mime-spoof
surface: api
tags: [upload, security, validation]
severity: high
---

**Pattern:** Server trusts client-supplied `Content-Type` header on
file upload; attacker uploads `evil.html` declared as `image/png`.
Server stores under image dir; victim opens URL → XSS in same origin.

**Failure mode:**
- POST `/api/upload` with `Content-Type: image/png` header but body is
  `<script>fetch('/api/me').then(...).then(send_to_attacker)</script>`.
- Backend writes to `/uploads/123.png`.
- Browser fetches; if MIME sniffing or `Content-Type: text/html` is
  served back, script runs in the app's origin.

**Edge cases test must cover:**
- Magic-byte detection (libmagic / file's first 16 bytes), not header.
- Reject upload if magic-byte mismatch with declared type.
- Strip EXIF / metadata from images server-side (steganography).
- Serve uploads with `Content-Disposition: attachment` OR from a
  separate cookie-less subdomain (`*.usercontent.tld`).
- Filename sanitization — reject path traversal (`..`, `/`).

**Reference:** OWASP File Upload Cheat Sheet.
