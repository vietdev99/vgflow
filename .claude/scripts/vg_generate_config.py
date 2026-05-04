#!/usr/bin/env python3
"""
vg_generate_config.py — Render .claude/vg.config.md from foundation JSON + template.

Called by /vg:project Round 7 (atomic config derivation).
Replaces the pre-v1.13.0 placeholder heredoc that left ~75% of the schema blank.

Usage:
  python3 .claude/scripts/vg_generate_config.py \
    --foundation .vg/.project-draft.json \
    --template   .claude/templates/vg/vg.config.template.md \
    --output     .claude/vg.config.md.staged

Foundation JSON schema (minimal required fields):
  {
    "project_name": "MyApp",
    "project_description": "...",
    "package_manager": "pnpm",
    "profile": "web-fullstack",
    "team_size": "solo",               # solo | 2-5 | 6-20 | 20+
    "hosting": "vps",                  # vps | vercel | cloudflare | railway | fly | aws | gcp | azure
    "domain": "myapp.example.com",
    "ssh_alias": "myapp-vps",
    "frontend": {"framework": "vite"},
    "backend":  {"framework": "fastify"},
    "data":     {"primary": "mongodb", "cache": "redis"},
    "monorepo": {"tool": "turborepo", "apps": ["web", "api"]},
    "auth":     {"roles": ["admin", "user"]},
    "i18n":     {"enabled": true, "default_locale": "en"},
    "critical_domains": "auth,billing"
  }

Every field has a sane default, so partial foundations still render a complete config.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


# ───────────────────────── Derivation tables ─────────────────────────
FRAMEWORK_PORT = {
    "vite": 5173, "next": 3000, "nuxt": 3000, "astro": 4321,
    "create-react-app": 3000, "vue-cli": 8080, "sveltekit": 5173,
    "remix": 3000, "qwik": 5173,
}
BACKEND_PORT = {
    "fastify": 3001, "express": 3000, "hono": 3001, "nestjs": 3000, "koa": 3000,
    "django": 8000, "fastapi": 8000, "flask": 5000, "rails": 3000,
    "gin": 8080, "echo": 8080, "axum": 3000, "actix": 8080,
    "none": 0,
}
BACKEND_HEALTH = {
    "fastify": "/health", "express": "/health", "hono": "/health",
    "nestjs": "/health", "django": "/health/", "fastapi": "/health",
    "flask": "/health", "rails": "/health",
    "gin": "/health", "echo": "/health", "axum": "/health", "actix": "/health",
    "none": "/",
}
DATA_PORT = {
    "mongodb": 27017, "postgres": 5432, "mysql": 3306, "sqlite": 0,
    "redis": 6379, "dynamodb": 0, "firestore": 0,
}
DATA_LOCAL_CHECK = {
    "mongodb": "mongosh --eval 'db.runCommand({ping:1})' --quiet 2>/dev/null",
    "postgres": "pg_isready -h localhost 2>/dev/null",
    "mysql": "mysqladmin ping -h localhost 2>/dev/null",
    "redis": "redis-cli ping 2>/dev/null",
    "clickhouse": "clickhouse-client --query 'SELECT 1' 2>/dev/null",
    "kafka": "kafka-topics.sh --bootstrap-server localhost:9092 --list 2>/dev/null | head -1",
}
HOSTING_DEPLOY_PROFILE = {
    "vps": "pm2", "vercel": "git_push", "cloudflare": "git_push",
    "railway": "git_push", "fly": "custom", "render": "git_push",
    "aws": "custom", "gcp": "custom", "azure": "custom",
    "heroku": "git_push", "netlify": "git_push",
}
TEST_RUNNER_BY_STACK = {
    "node": "npx vitest run",
    "python": "pytest",
    "go": "go test ./...",
    "rust": "cargo test",
    "java": "./gradlew test",
    "ruby": "bundle exec rspec",
}


# ───────────────────────── Helpers ─────────────────────────
def _get(d: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Nested dict lookup: _get(f, 'backend.framework', 'fastify')."""
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
        if cur is None:
            return default
    return cur


def _stack_from_framework(fw: str) -> str:
    if fw in ("vite", "next", "nuxt", "astro", "create-react-app", "vue-cli",
              "sveltekit", "remix", "qwik", "fastify", "express", "hono",
              "nestjs", "koa"):
        return "node"
    if fw in ("django", "fastapi", "flask"):
        return "python"
    if fw in ("gin", "echo"):
        return "go"
    if fw in ("axum", "actix"):
        return "rust"
    if fw in ("rails",):
        return "ruby"
    return "node"


# ───────────────────────── Block renderers ─────────────────────────
def render_crossai_clis(team_size: str) -> str:
    if team_size == "solo":
        clis = [
            ("Claude", 'cat {context} | claude --model sonnet -p "{prompt}"', "Claude Sonnet 4.6"),
        ]
    elif team_size in ("2-5",):
        clis = [
            ("Codex", 'cat {context} | codex exec "{prompt}"', "Codex configured model"),
            ("Claude", 'cat {context} | claude --model sonnet -p "{prompt}"', "Claude Sonnet 4.6"),
        ]
    else:
        clis = [
            ("Codex", 'cat {context} | codex exec "{prompt}"', "Codex configured model"),
            ("Gemini", 'cat {context} | gemini -m gemini-3.1-pro-preview -p "{prompt}" --yolo', "Gemini Pro High 3.1"),
            ("Claude", 'cat {context} | claude --model sonnet -p "{prompt}"', "Claude Sonnet 4.6"),
        ]
    lines = ["crossai_clis:"]
    for name, cmd, label in clis:
        lines.append(f'  - name: "{name}"')
        lines.append(f"    command: '{cmd}'")
        lines.append(f'    label: "{label}"')
    return "\n".join(lines)


def render_models_block(team_size: str) -> str:
    if team_size == "solo":
        models = {
            "planner": "opus", "contract_gen": "sonnet", "test_goals": "sonnet",
            "executor": "sonnet", "debugger": "opus", "scanner": "haiku",
            "test_codegen": "sonnet",
        }
    else:
        models = {
            "planner": "opus", "contract_gen": "opus", "test_goals": "sonnet",
            "executor": "opus", "debugger": "opus", "scanner": "haiku",
            "test_codegen": "sonnet",
        }
    lines = ["models:"]
    notes = {
        "planner": "blueprint 2a — plan quality drives everything",
        "contract_gen": "blueprint 2b — follow format template",
        "test_goals": "blueprint 2b5 — convert decisions to goals",
        "executor": "build step 8 — copy contracts + follow rules",
        "debugger": "build step 9 — post-wave failure needs reasoning",
        "scanner": "review phase 1/2 — parallel scanners",
        "test_codegen": "test step — generate Playwright from specs",
    }
    for k, v in models.items():
        lines.append(f'  {k}: "{v}"           # {notes[k]}')
    return "\n".join(lines)


def render_services_block(foundation: Dict[str, Any]) -> str:
    data_primary = _get(foundation, "data.primary", "mongodb")
    cache = _get(foundation, "data.cache")
    queue = _get(foundation, "data.queue") or _get(foundation, "backend.queue")
    backend_port = BACKEND_PORT.get(_get(foundation, "backend.framework", "fastify"), 3001)
    backend_health = BACKEND_HEALTH.get(_get(foundation, "backend.framework", "fastify"), "/health")

    def svc(name: str, check: str, required: bool = True) -> List[str]:
        return [
            f'    - name: "{name}"',
            f'      check: "{check}"',
            f"      required: {'true' if required else 'false'}",
        ]

    lines = ["services:", "  local:"]
    lines += svc("API", f"curl -sf http://localhost:{backend_port}{backend_health}", True)
    if data_primary and data_primary != "none":
        lines += svc(data_primary.capitalize(), DATA_LOCAL_CHECK.get(data_primary, "true"), True)
    if cache:
        lines += svc(cache.capitalize(), DATA_LOCAL_CHECK.get(cache, "true"), True)
    if queue:
        lines += svc(queue.capitalize(), DATA_LOCAL_CHECK.get(queue, "true"), False)

    lines.append("  sandbox:")
    lines += svc("API", f"curl -sf http://localhost:{backend_port}{backend_health}", True)
    if data_primary and data_primary != "none":
        lines += svc(data_primary.capitalize(), DATA_LOCAL_CHECK.get(data_primary, "true"), True)
    if cache:
        lines += svc(cache.capitalize(), DATA_LOCAL_CHECK.get(cache, "true"), True)
    if queue:
        lines += svc(queue.capitalize(), DATA_LOCAL_CHECK.get(queue, "true"), False)
    return "\n".join(lines)


def render_credentials_block(foundation: Dict[str, Any]) -> str:
    roles = _get(foundation, "auth.roles") or ["admin", "user"]
    domain = _get(foundation, "domain", "example.com")
    fe_port = FRAMEWORK_PORT.get(_get(foundation, "frontend.framework", "vite"), 5173)

    def cred(role: str, host: str) -> List[str]:
        safe_role = role.lower().replace("_", "").replace("-", "")
        return [
            f'    - role: "{role}"',
            f'      domain: "{host}"',
            f'      email: "{safe_role}@{domain}"',
            f'      password: "{role.capitalize()}123!"',
        ]

    lines = ["credentials:", "  local:"]
    for r in roles:
        lines += cred(r, f"localhost:{fe_port}")
    lines.append("  sandbox:")
    for r in roles:
        lines += cred(r, domain)
    return "\n".join(lines)


def render_apps_block(foundation: Dict[str, Any]) -> str:
    apps = _get(foundation, "monorepo.apps") or ["web", "api"]
    tool = _get(foundation, "monorepo.tool", "turborepo")
    lines = ["apps:"]
    for app in apps:
        stack = _stack_from_framework(
            _get(foundation, "frontend.framework" if app == "web" else "backend.framework", "vite")
        )
        if tool == "turborepo":
            build = f"turbo run build --filter={app}"
            test = f"turbo run test --filter={app}"
        else:
            build = f"{_get(foundation, 'package_manager', 'pnpm')} --filter {app} build"
            test = f"{_get(foundation, 'package_manager', 'pnpm')} --filter {app} test"
        lines.append(f"  {app}:")
        lines.append(f'    path: "apps/{app}"')
        lines.append(f'    build: "{build}"')
        lines.append(f'    test: "{test}"')
        lines.append(f'    type: "{stack}"')
    return "\n".join(lines)


def render_infra_deps_block(foundation: Dict[str, Any]) -> str:
    items: List[tuple[str, str, str]] = []
    primary = _get(foundation, "data.primary")
    cache = _get(foundation, "data.cache")
    queue = _get(foundation, "data.queue") or _get(foundation, "backend.queue")
    for svc in (primary, cache, queue):
        if svc and svc != "none" and svc in DATA_LOCAL_CHECK:
            items.append((svc, DATA_LOCAL_CHECK[svc], svc.capitalize()))
    if not items:
        return ""
    lines = []
    for name, check, label in items:
        lines.append(f"    {name}:")
        lines.append(f'      check_local: "{check}"')
        lines.append(f'      check_sandbox: "{check}"')
        lines.append(f'      label: "{label}"')
    return "\n".join(lines)


# ───────────────────────── Main rendering ─────────────────────────
def substitute_tokens(template: str, foundation: Dict[str, Any]) -> str:
    fe_fw = _get(foundation, "frontend.framework", "vite")
    be_fw = _get(foundation, "backend.framework", "fastify")
    data_primary = _get(foundation, "data.primary", "mongodb")
    team_size = _get(foundation, "team_size", "solo")
    hosting = _get(foundation, "hosting", "vps")
    pm = _get(foundation, "package_manager", "pnpm")
    host_os = _get(foundation, "env.local.os") or ("linux" if hosting in ("vps",) else "darwin")

    subs: Dict[str, Any] = {
        "project_name": _get(foundation, "project_name", "MyProject"),
        "project_description": _get(foundation, "project_description", ""),
        "package_manager": pm,
        "profile": _get(foundation, "profile", "web-fullstack"),
        "domain": _get(foundation, "domain", "example.com"),
        "ssh_alias": _get(foundation, "ssh_alias", "your-vps"),
        "db_name": _get(foundation, "db_name") or _get(foundation, "project_name", "project1").lower().replace(" ", ""),
        "ports.database": DATA_PORT.get(data_primary, 0),
        "backend.port": BACKEND_PORT.get(be_fw, 3001),
        "backend.health": BACKEND_HEALTH.get(be_fw, "/health"),
        "backend.framework": be_fw,
        "frontend.port": FRAMEWORK_PORT.get(fe_fw, 5173),
        "frontend.framework": fe_fw,
        "deploy_profile": HOSTING_DEPLOY_PROFILE.get(hosting, "custom"),
        "env.local.os": host_os,
        "test_runner_local": TEST_RUNNER_BY_STACK.get(_stack_from_framework(be_fw), "npx vitest run"),
        "test_runner_sandbox": TEST_RUNNER_BY_STACK.get(_stack_from_framework(be_fw), "pnpm test"),
        "sandbox.project_path": _get(foundation, "sandbox.project_path") or f"/home/deploy/{_get(foundation, 'project_name', 'project1').lower().replace(' ', '')}",
        "deploy.restart_cmd": _deploy_restart_cmd(hosting, _get(foundation, "project_name", "project1")),
        "deploy.rollback_cmd": _deploy_rollback_cmd(hosting),
        "critical_domains": _get(foundation, "critical_domains", "auth,billing"),
        "contract_format.type": _get(foundation, "contract_format.type")
            or ("zod_code_block" if _stack_from_framework(be_fw) == "node" else "openapi_yaml"),
        "contract_format.compile_cmd": _get(foundation, "contract_format.compile_cmd")
            or _contract_compile_cmd(pm, be_fw),
        "build_gates.typecheck_cmd": _get(foundation, "build_gates.typecheck_cmd")
            or _typecheck_cmd(pm, _get(foundation, "monorepo.tool", "turborepo")),
        "build_gates.build_cmd": _get(foundation, "build_gates.build_cmd")
            or f"{pm} turbo build" if _get(foundation, "monorepo.tool") == "turborepo" else f"{pm} build",
        "build_gates.test_unit_cmd": _get(foundation, "build_gates.test_unit_cmd")
            or (f"{pm} turbo test:unit" if _get(foundation, "monorepo.tool") == "turborepo" else f"{pm} test"),
        "i18n.enabled": "true" if _get(foundation, "i18n.enabled", False) else "false",
        "i18n.default_locale": _get(foundation, "i18n.default_locale", "en"),
    }

    def repl(m: re.Match) -> str:
        key = m.group(1).strip()
        val = subs.get(key)
        if val is None:
            val = _get(foundation, key)
        return str(val) if val is not None else m.group(0)

    rendered = re.sub(r"\{\{([^{}]+?)\}\}", repl, template)

    rendered = rendered.replace("# ⟪ CROSSAI_CLIS_BLOCK ⟫", render_crossai_clis(team_size))
    rendered = rendered.replace("# ⟪ MODELS_BLOCK ⟫", render_models_block(team_size))
    rendered = rendered.replace("# ⟪ SERVICES_BLOCK ⟫", render_services_block(foundation))
    rendered = rendered.replace("# ⟪ CREDENTIALS_BLOCK ⟫", render_credentials_block(foundation))
    rendered = rendered.replace("# ⟪ APPS_BLOCK ⟫", render_apps_block(foundation))
    rendered = rendered.replace("    # ⟪ INFRA_DEPS_BLOCK ⟫", render_infra_deps_block(foundation) or "    # (no infra services auto-detected from foundation)")

    return rendered


def _deploy_restart_cmd(hosting: str, project_name: str) -> str:
    slug = project_name.lower().replace(" ", "-")
    if hosting == "vps":
        return f"pm2 reload {slug}-api --update-env"
    if hosting in ("vercel", "netlify", "cloudflare"):
        return "# auto-deployed on git push"
    if hosting == "fly":
        return "flyctl deploy"
    return f"# customize for {hosting}"


def _deploy_rollback_cmd(hosting: str) -> str:
    if hosting == "vps":
        return "pm2 stop all && git checkout {prev_sha} && pnpm install && pnpm run build && pm2 reload all --update-env"
    return f"# customize rollback for {hosting}"


def _contract_compile_cmd(pm: str, be_fw: str) -> str:
    stack = _stack_from_framework(be_fw)
    if stack == "node":
        return f"{pm} exec tsc --noEmit"
    if stack == "python":
        return "python -m py_compile"
    if stack == "rust":
        return "cargo check"
    if stack == "go":
        return "go build ./..."
    return "# customize contract compile command"


def _typecheck_cmd(pm: str, monorepo_tool: str) -> str:
    if monorepo_tool == "turborepo":
        return f"{pm} turbo typecheck"
    if monorepo_tool == "nx":
        return f"{pm} nx run-many -t typecheck"
    return f"{pm} typecheck"


def strip_template_header(content: str) -> str:
    """Remove the template-only header comment block (keep the --- frontmatter)."""
    lines = content.splitlines(keepends=True)
    out = []
    in_template_header = False
    for line in lines:
        if line.startswith("# VG Workflow Config — Template"):
            in_template_header = True
            continue
        if in_template_header:
            if line.startswith("# Rendered by") or line.startswith("# Foundation-derived") \
                    or line.startswith("# After generation") or line.startswith("#") \
                    or line.startswith("# Token schema") or line.startswith("#   ") \
                    or line.startswith("# CROSSAI_CLIS_BLOCK") or line.startswith("# Remove this header") \
                    or line.strip() == "":
                if line.startswith("# === Project Identity"):
                    in_template_header = False
                    out.append("# VG Workflow Config — Project-specific variables\n")
                    out.append("# Generated by /vg:project Round 7 via vg_generate_config.py.\n")
                    out.append("# Edit freely — workflow re-reads every command; no regeneration needed unless foundation changes.\n")
                    out.append("\n")
                    out.append(line)
                continue
            else:
                in_template_header = False
                out.append(line)
        else:
            out.append(line)
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render vg.config.md from foundation JSON + template")
    ap.add_argument("--foundation", required=True, help="Path to foundation JSON")
    ap.add_argument("--template", default=".claude/templates/vg/vg.config.template.md",
                    help="Template path (default: .claude/templates/vg/vg.config.template.md)")
    ap.add_argument("--output", default=".claude/vg.config.md.staged",
                    help="Output path (default: .claude/vg.config.md.staged)")
    ap.add_argument("--strict", action="store_true",
                    help="Fail if any {{token}} remains unresolved after substitution")
    args = ap.parse_args()

    foundation_path = Path(args.foundation)
    template_path = Path(args.template)
    output_path = Path(args.output)

    if not foundation_path.exists():
        print(f"ERROR: foundation not found: {foundation_path}", file=sys.stderr)
        return 1
    if not template_path.exists():
        print(f"ERROR: template not found: {template_path}", file=sys.stderr)
        return 1

    foundation = json.loads(foundation_path.read_text(encoding="utf-8"))
    template = template_path.read_text(encoding="utf-8")

    rendered = substitute_tokens(template, foundation)
    rendered = strip_template_header(rendered)

    unresolved = re.findall(r"\{\{[^{}]+?\}\}", rendered)
    if unresolved:
        msg = f"WARN: {len(unresolved)} unresolved tokens: {unresolved[:5]}..."
        print(msg, file=sys.stderr)
        if args.strict:
            return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")

    print(f"OK rendered={output_path} bytes={len(rendered)} unresolved={len(unresolved)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
