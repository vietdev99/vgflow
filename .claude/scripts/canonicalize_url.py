#!/usr/bin/env python3
"""canonicalize_url.py — strip volatile params, normalize URL for memoization.

Usage: canonicalize_url.py <url>
Outputs canonical form to stdout.
"""
import sys
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

VOLATILE_PARAMS = {
    "t", "_t", "ts", "timestamp", "session", "session_id", "sessionid",
    "request_id", "rid", "trace_id", "nonce", "_", "cb", "cachebust",
    "csrf", "_csrf", "auth_token", "token",
}

def canonicalize(url: str) -> str:
    p = urlparse(url)
    netloc = p.netloc.lower()
    path = p.path.rstrip("/")
    qs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
          if k.lower() not in VOLATILE_PARAMS]
    qs.sort()
    return urlunparse((p.scheme.lower(), netloc, path, "", urlencode(qs), ""))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: canonicalize_url.py <url>", file=sys.stderr)
        sys.exit(2)
    print(canonicalize(sys.argv[1]))
