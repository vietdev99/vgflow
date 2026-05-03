"""4 auth kinds for recipe execution (RFC v9 D2/D9).

Each handler returns a `requests.Session` (or compatible) with auth applied,
plus optional `auth_verify` step to confirm credentials are valid before
executing the recipe (D2 portability — fail fast on bad creds).

Auth kinds:
- cookie_login: POST /login → captured Set-Cookie, attached as session.cookies.
- api_key:      static header `Authorization: ApiKey {key}` or per-config name.
- bearer_jwt:   POST /auth/token → captured `access_token`, set Authorization.
                Token refresh on 401 → re-runs login.
- command:      project-supplied auth-plugin.sh emits cookie/token to stdout.
                Runner trusts the script. Sandbox-only by D9 — main env reject.

All handlers honor X-VGFlow-Sandbox: true (D9 sandbox safety) — the
executor wires this into every outgoing request when env=sandbox.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]


class AuthError(Exception):
    """Auth step failed (login 4xx/5xx, command non-zero, missing creds)."""


@dataclass
class AuthContext:
    """Result of an auth handler. Wraps a requests.Session ready to use."""
    session: Any  # requests.Session
    role: str
    refresh_callable: Callable[[], None] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _ensure_requests():
    if requests is None:
        raise ImportError(
            "requests required for recipe execution — install with `pip install requests>=2.31`"
        )


def _new_session() -> Any:
    _ensure_requests()
    s = requests.Session()
    # Identifier so backend logs show vgflow recipe traffic
    s.headers["User-Agent"] = "vgflow-recipe-runtime/1.0"
    return s


def _apply_sandbox_header(session: Any, sandbox: bool) -> None:
    if sandbox:
        session.headers["X-VGFlow-Sandbox"] = "true"


def auth_cookie_login(
    base_url: str,
    creds: dict[str, Any],
    sandbox: bool = False,
) -> AuthContext:
    """POST creds.endpoint with creds.body; relies on Set-Cookie."""
    _ensure_requests()
    endpoint = creds.get("endpoint") or "/login"
    body = creds.get("body") or {}
    session = _new_session()
    _apply_sandbox_header(session, sandbox)
    url = base_url.rstrip("/") + endpoint
    resp = session.post(url, json=body, timeout=10)
    if resp.status_code >= 400:
        raise AuthError(
            f"cookie_login failed: POST {endpoint} → {resp.status_code} "
            f"{resp.text[:200]}"
        )
    if not session.cookies:
        raise AuthError(
            f"cookie_login {endpoint} returned {resp.status_code} but no Set-Cookie "
            f"headers — backend may not be cookie-based?"
        )
    return AuthContext(session=session, role=creds.get("role", "unknown"))


def auth_api_key(
    base_url: str,
    creds: dict[str, Any],
    sandbox: bool = False,
) -> AuthContext:
    """Header-based API key. Default Authorization: ApiKey {key}.

    creds:
      key: <required>
      header_name: Authorization (default)
      scheme: ApiKey (default; set "" for raw key)
    """
    _ensure_requests()
    key = creds.get("key")
    if not key:
        raise AuthError("api_key auth requires creds.key")
    header_name = creds.get("header_name", "Authorization")
    scheme = creds.get("scheme", "ApiKey")
    value = f"{scheme} {key}".strip() if scheme else key
    session = _new_session()
    session.headers[header_name] = value
    _apply_sandbox_header(session, sandbox)
    return AuthContext(session=session, role=creds.get("role", "unknown"))


def auth_bearer_jwt(
    base_url: str,
    creds: dict[str, Any],
    sandbox: bool = False,
) -> AuthContext:
    """POST creds.endpoint → capture access_token → Authorization: Bearer ...

    Refresh callable retries the login on 401. Recipe executor invokes
    refresh once; if 401 persists, raises AuthError.
    """
    _ensure_requests()
    endpoint = creds.get("endpoint") or "/auth/token"
    body = creds.get("body") or {}
    token_path = creds.get("token_path", "access_token")

    session = _new_session()
    _apply_sandbox_header(session, sandbox)

    def _login() -> None:
        url = base_url.rstrip("/") + endpoint
        resp = session.post(url, json=body, timeout=10)
        if resp.status_code >= 400:
            raise AuthError(
                f"bearer_jwt login failed: POST {endpoint} → {resp.status_code}"
            )
        try:
            payload = resp.json()
        except Exception as e:
            raise AuthError(f"bearer_jwt response not JSON: {e}") from e
        token = payload
        for part in token_path.split("."):
            if not isinstance(token, dict) or part not in token:
                raise AuthError(
                    f"bearer_jwt token_path='{token_path}' did not resolve "
                    f"in response: {list(payload.keys())[:5]}"
                )
            token = token[part]
        if not isinstance(token, str) or not token:
            raise AuthError(f"bearer_jwt resolved token is not a non-empty string")
        session.headers["Authorization"] = f"Bearer {token}"

    _login()
    return AuthContext(
        session=session,
        role=creds.get("role", "unknown"),
        refresh_callable=_login,
    )


def auth_command(
    base_url: str,
    creds: dict[str, Any],
    sandbox: bool = False,
) -> AuthContext:
    """Run external command; expect JSON on stdout: {kind, header|cookies}.

    D9 SAFETY: command auth is sandbox-only. main/prod env raises AuthError.

    creds.command: shell command (must be in PATH or absolute).
    creds.timeout: seconds (default 30).
    """
    if not sandbox:
        raise AuthError(
            "auth kind 'command' is sandbox-only (D9 hard gate). "
            "Project must define separate creds for main env."
        )
    cmd = creds.get("command")
    if not cmd:
        raise AuthError("auth kind 'command' requires creds.command")
    timeout = int(creds.get("timeout", 30))

    args = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
    # Codex-R4-HIGH-5 fix: scrub env so the project's auth-plugin command
    # does NOT inherit caller's secrets (CLAUDE_API_KEY, AWS_*, etc.).
    # Allowlist + opt-in passthrough via creds.env_passthrough.
    _AUTH_CMD_ENV_ALLOW = {
        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM",
        "LANG", "LC_ALL", "TMPDIR", "PWD",
    }
    passthrough = creds.get("env_passthrough") or []
    if isinstance(passthrough, str):
        passthrough = [k.strip() for k in passthrough.split(",") if k.strip()]
    scrubbed_env = {
        k: v for k, v in os.environ.items()
        if k in _AUTH_CMD_ENV_ALLOW or k in set(passthrough)
    }
    scrubbed_env["VGFLOW_RECIPE_RUNTIME"] = "1"
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=scrubbed_env,
    )
    if proc.returncode != 0:
        raise AuthError(
            f"auth command exited {proc.returncode}: {proc.stderr[:300]}"
        )

    import json as _json
    try:
        payload = _json.loads(proc.stdout)
    except _json.JSONDecodeError as e:
        raise AuthError(
            f"auth command stdout not JSON: {e} (stdout={proc.stdout[:200]!r})"
        ) from e

    session = _new_session()
    _apply_sandbox_header(session, sandbox)
    kind = payload.get("kind", "header")
    if kind == "header":
        for name, value in (payload.get("headers") or {}).items():
            session.headers[name] = value
    elif kind == "cookies":
        for name, value in (payload.get("cookies") or {}).items():
            session.cookies.set(name, value)
    else:
        raise AuthError(f"auth command unknown kind={kind}")

    return AuthContext(
        session=session,
        role=creds.get("role", "command-supplied"),
        metadata={"auth_command": cmd},
    )


_HANDLERS: dict[str, Callable[..., AuthContext]] = {
    "cookie_login": auth_cookie_login,
    "api_key": auth_api_key,
    "bearer_jwt": auth_bearer_jwt,
    "command": auth_command,
}


def authenticate(
    kind: str,
    base_url: str,
    creds: dict[str, Any],
    sandbox: bool = False,
) -> AuthContext:
    """Dispatch to one of the 4 auth handlers."""
    handler = _HANDLERS.get(kind)
    if handler is None:
        raise AuthError(
            f"Unknown auth kind '{kind}' — must be one of {sorted(_HANDLERS)}"
        )
    return handler(base_url, creds, sandbox=sandbox)
