#!/usr/bin/env python3
"""
review-fixture-bootstrap.py — v2.35.0 auth bootstrap for CRUD round-trip review.

Issues ephemeral auth tokens per role declared in vg.config.md, writes them
to ${PHASE_DIR}/.review-fixtures/tokens.local.yaml (gitignored). Workers
spawned by spawn-crud-roundtrip.py read this file to authenticate.

Reasons creds are NOT in vg.config.md:
- vg.config.md is committed; secrets must not be
- Tokens are ephemeral (TTL'd) so refresh per session is cheap
- Different environments (local/staging) use different users without config diff

Inputs (vg.config.md):
  review:
    roles: ["admin", "user", "anon"]
    auth:
      login_endpoint: "POST /api/auth/login"
      base_url: "http://localhost:3001"
      seed_users_path: ".review-fixtures/seed-users.local.yaml"   # gitignored
      token_ttl_seconds: 3600

Inputs (.review-fixtures/seed-users.local.yaml — gitignored, user-managed):
  admin:
    email: "admin@test.local"
    password: "..."
  user:
    email: "user@test.local"
    password: "..."
  # anon: null  (no login)

Output (.review-fixtures/tokens.local.yaml — gitignored, regenerated per run):
  admin:
    token: "Bearer ..."
    user_id: "u-001"
    tenant_id: "t-001"
    issued_at: "2026-04-30T12:00:00Z"
    expires_at: "2026-04-30T13:00:00Z"
  user:
    token: "Bearer ..."
    ...

Usage:
  review-fixture-bootstrap.py                    # uses cwd as VG_REPO_ROOT
  review-fixture-bootstrap.py --phase-dir <path>
  review-fixture-bootstrap.py --check            # validate seed file exists, no token issuance
  review-fixture-bootstrap.py --json

Exit codes:
  0 — tokens written (or --check passed)
  1 — config/seed missing or login failed
  2 — arg error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_review_config() -> dict:
    cfg_path = REPO_ROOT / ".claude" / "vg.config.md"
    if not cfg_path.is_file():
        return {}
    text = cfg_path.read_text(encoding="utf-8", errors="replace")
    out: dict = {}
    roles_match = re.search(r"^review:\s*\n((?:[ \t]+.+\n)+)", text, re.M)
    if not roles_match:
        return {}
    block = roles_match.group(1)
    rm = re.search(r"^\s*roles:\s*\[([^\]]*)\]", block, re.M)
    if rm:
        out["roles"] = [r.strip().strip('"').strip("'") for r in rm.group(1).split(",") if r.strip()]
    bm = re.search(r"^\s*base_url:\s*[\"']?([^\"'\s]+)", block, re.M)
    if bm:
        out["base_url"] = bm.group(1)
    lm = re.search(r"^\s*login_endpoint:\s*[\"']?([^\"']+)[\"']?", block, re.M)
    if lm:
        out["login_endpoint"] = lm.group(1).strip()
    sm = re.search(r"^\s*seed_users_path:\s*[\"']?([^\"'\s]+)", block, re.M)
    if sm:
        out["seed_users_path"] = sm.group(1)
    tm = re.search(r"^\s*token_ttl_seconds:\s*(\d+)", block, re.M)
    if tm:
        out["token_ttl_seconds"] = int(tm.group(1))
    return out


def load_seed_users(seed_path: Path) -> dict:
    if not seed_path.is_file():
        return {}
    try:
        import yaml
    except ImportError:
        print("\033[38;5;208mpyyaml required for seed users parsing — pip install pyyaml\033[0m", file=sys.stderr)
        return {}
    return yaml.safe_load(seed_path.read_text(encoding="utf-8")) or {}


def issue_token(base_url: str, login_endpoint: str, email: str, password: str) -> dict | None:
    method, path = login_endpoint.split(maxsplit=1)
    url = base_url.rstrip("/") + path
    payload = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method=method.upper(),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  \033[33mlogin failed for {email}: HTTP {e.code} {e.reason}\033[0m", file=sys.stderr)
        return None
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"  \033[33mlogin error for {email}: {e}\033[0m", file=sys.stderr)
        return None

    token = body.get("token") or body.get("access_token") or body.get("Authorization")
    if not token:
        print(f"  \033[33mlogin response for {email} has no token field\033[0m", file=sys.stderr)
        return None

    if not token.startswith("Bearer "):
        token = f"Bearer {token}"

    return {
        "token": token,
        "user_id": body.get("user_id") or body.get("id") or "unknown",
        "tenant_id": body.get("tenant_id") or body.get("org_id"),
        "issued_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def write_tokens(out_path: Path, tokens: dict, ttl_seconds: int) -> None:
    expires_at = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for entry in tokens.values():
        if entry is not None:
            entry["expires_at"] = expires_at

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        body = yaml.safe_dump(tokens, default_flow_style=False, sort_keys=True)
    except ImportError:
        body = json.dumps(tokens, indent=2)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(out_path)
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        pass


def ensure_gitignore(repo_root: Path) -> None:
    gi = repo_root / ".gitignore"
    needle = ".review-fixtures/"
    if gi.is_file():
        if needle in gi.read_text(encoding="utf-8", errors="replace"):
            return
        with gi.open("a", encoding="utf-8") as f:
            f.write(f"\n# v2.35.0 review fixtures (ephemeral auth tokens)\n{needle}\n")
    else:
        gi.write_text(f"# v2.35.0 review fixtures (ephemeral auth tokens)\n{needle}\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", help="Phase dir (default: VG_PHASE_DIR env or .vg/phases/{N})")
    ap.add_argument("--check", action="store_true", help="Validate config + seed users present, do not issue tokens")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg = load_review_config()
    if not cfg.get("roles"):
        print("\033[38;5;208mvg.config.md → review.roles missing or empty.\033[0m", file=sys.stderr)
        return 1

    base_url = cfg.get("base_url")
    login_endpoint = cfg.get("login_endpoint", "POST /api/auth/login")
    seed_path = REPO_ROOT / cfg.get("seed_users_path", ".review-fixtures/seed-users.local.yaml")
    ttl = cfg.get("token_ttl_seconds", 3600)

    ensure_gitignore(REPO_ROOT)

    if args.check:
        if not seed_path.is_file():
            print(f"\033[38;5;208mSeed users file not found: {seed_path}\033[0m", file=sys.stderr)
            print(f"   Create it with admin/user credentials. See vg.config.template.md.", file=sys.stderr)
            return 1
        seed = load_seed_users(seed_path)
        missing = [r for r in cfg["roles"] if r != "anon" and r not in seed]
        if missing:
            print(f"\033[38;5;208mSeed file missing roles: {missing}\033[0m", file=sys.stderr)
            return 1
        if not args.quiet:
            print(f"✓ Seed file OK: {len(seed)} role(s) declared.")
        return 0

    if not base_url:
        print("\033[38;5;208mvg.config.md → review.auth.base_url missing.\033[0m", file=sys.stderr)
        return 1

    seed = load_seed_users(seed_path)
    if not seed:
        print(f"\033[38;5;208mSeed users file missing or empty: {seed_path}\033[0m", file=sys.stderr)
        return 1

    tokens: dict = {}
    failed_roles: list[str] = []

    for role in cfg["roles"]:
        if role == "anon":
            tokens[role] = None
            continue
        creds = seed.get(role)
        if not creds:
            print(f"  ⚠ no seed credentials for role '{role}' — skipping", file=sys.stderr)
            failed_roles.append(role)
            continue
        if not args.quiet:
            print(f"  Issuing token for role '{role}' ({creds.get('email')})...")
        tok = issue_token(base_url, login_endpoint, creds["email"], creds["password"])
        if tok is None:
            failed_roles.append(role)
            continue
        tokens[role] = tok

    phase_dir_arg = args.phase_dir or os.environ.get("VG_PHASE_DIR")
    if phase_dir_arg:
        out_dir = Path(phase_dir_arg).resolve() / ".review-fixtures"
    else:
        out_dir = REPO_ROOT / ".review-fixtures"
    out_path = out_dir / "tokens.local.yaml"
    write_tokens(out_path, tokens, ttl)

    if args.json:
        print(json.dumps({
            "tokens_path": str(out_path.resolve().relative_to(REPO_ROOT).as_posix()) if str(out_path.resolve()).startswith(str(REPO_ROOT)) else str(out_path),
            "roles": list(tokens.keys()),
            "failed_roles": failed_roles,
            "expires_in_seconds": ttl,
        }, indent=2))
    elif not args.quiet:
        print(f"✓ Tokens written: {out_path}")
        print(f"  Roles: {', '.join(tokens.keys())}")
        if failed_roles:
            print(f"  ⚠ Failed: {', '.join(failed_roles)}")

    return 1 if failed_roles else 0


if __name__ == "__main__":
    sys.exit(main())
