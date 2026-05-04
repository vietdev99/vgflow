#!/usr/bin/env python3
"""
vg_deploy_aggregator.py — merge per-phase DEPLOY-RUNBOOKs → project-wide lessons (v1.14.0+ C.4)

Step 8 (this script, core):
  - .vg/DEPLOY-LESSONS.md       — 3 views (by-service / by-topic / dependency-graph ASCII)
  - .vg/ENV-CATALOG.md          — 8-column env var lifecycle

Step 9 (extras, same script added later):
  - .vg/DEPLOY-FAILURE-REGISTER.md
  - .vg/DEPLOY-RECIPES.md
  - .vg/DEPLOY-PERF-BASELINE.md
  - .vg/SMOKE-PACK.md

Inputs:
  - .vg/phases/*/DEPLOY-RUNBOOK.md   (canonical, post-accept)
  - .vg/phases/*/.deploy-log.txt     (raw log, fallback if RUNBOOK missing)
  - .vg/phases/*/SPECS.md            (service + env var hints)
  - .vg/phases/*/CONTEXT.md          (decisions + dependency graph edges)

Idempotent: re-run rewrites output files entirely (no append dup).
"""
from __future__ import annotations

import sys
import re
import argparse
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


VG_ROOT = Path(".vg")
PHASES_DIR = VG_ROOT / "phases"
CONFIG_PATH = Path(".claude") / "vg.config.md"


def _load_sandbox_runtime_keys() -> tuple[str, str]:
    """Read sandbox SSH alias + project path from vg.config.md.

    Returns:
      (ssh_alias, project_path)

    Falls back to a hard-coded default tuple only if the config file is
    missing or keys unparseable — but config is the source of truth. Per
    CLAUDE.md infra rule "Workflow = engine, no hardcode", this never bakes
    the literal into output strings. The fallback exists only to keep the
    aggregator runnable when invoked outside a configured project (tests).
    See `.vg/HARDCODE-REGISTER.md` §4 for the literal values.
    """
    # INTENTIONAL_HARDCODE: docstring example + helper fallback (Phase K1 register §4)
    fallback_alias, fallback_path = "vollx", "/home/vollx/vollxssp"
    if not CONFIG_PATH.exists():
        return fallback_alias, fallback_path
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fallback_alias, fallback_path

    # Best-effort YAML lookup — match `sandbox:` block then `run_prefix` / `project_path`
    sandbox_re = re.compile(
        r'(?ms)^\s*sandbox:\s*$\n((?:\s{2,}[^\n]+\n)+)',
    )
    m = sandbox_re.search(text)
    if not m:
        return fallback_alias, fallback_path
    block = m.group(1)
    alias = fallback_alias
    path = fallback_path
    rp = re.search(r'run_prefix:\s*["\']?([^"\'\n]+)', block)
    if rp:
        # run_prefix is "ssh vollx"; strip leading verb to extract alias
        rp_val = rp.group(1).strip()
        rp_parts = rp_val.split()
        if len(rp_parts) >= 2 and rp_parts[0] == "ssh":
            alias = rp_parts[1]
    pp = re.search(r'project_path:\s*["\']?([^"\'\n]+)', block)
    if pp:
        path = pp.group(1).strip()
    return alias, path

# Service inference patterns — heuristic map phase name/SPECS hints → service
SERVICE_HINTS = [
    ("apps/api",        [r"\bapi\b", r"fastify", r"modules?/", r"REST\s+API"]),
    ("apps/web",        [r"\bweb\b", r"\bdashboard\b", r"\bpage\b", r"\bReact\b", r"\bFE\b", r"\badvertiser\b", r"\bpublisher\b", r"\badmin\b"]),
    ("apps/rtb-engine", [r"\brtb[_-]?engine\b", r"\baxum\b", r"\bbid\s+request\b", r"\bauction\b"]),
    ("apps/workers",    [r"\bworkers?\b", r"\bconsumer\b", r"\bkafka\s+consumer\b", r"\bcron\b"]),
    ("apps/pixel",      [r"\bpixel\b", r"\bpostback\b", r"\btracking\b"]),
    ("infra/clickhouse",[r"\bclickhouse\b", r"\bOLAP\b", r"\banalytic\b"]),
    ("infra/mongodb",   [r"\bmongo(?:db)?\b", r"\bcollection\b"]),
    ("infra/kafka",     [r"\bkafka\b", r"\btopic\b", r"\bpartition\b"]),
    ("infra/redis",     [r"\bredis\b", r"\bcache\b"]),
]

# Env var patterns — UPPER_CASE, min 4 chars, likely not a keyword
ENV_VAR_RE = re.compile(r"\b([A-Z][A-Z0-9_]{3,})\b")
# Reject common ALL-CAPS noise
ENV_BLOCKLIST = {
    "HTTP", "HTTPS", "API", "URL", "URI", "JSON", "XML", "HTML", "CSS", "DOM", "SQL",
    "REST", "CRUD", "UUID", "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS",
    "NOSQL", "TTL", "CDN", "DNS", "VPN", "SSH", "SSL", "TLS", "JWT", "OAUTH",
    "UTC", "UTF", "ASCII", "TODO", "FIXME", "NOTE", "WARN", "ERROR", "DEBUG",
    "TRUE", "FALSE", "NULL", "NONE", "YES", "NO", "OK",
    "README", "CHANGELOG", "LICENSE", "FOUNDATION", "CONTEXT", "SPECS", "PLAN",
    "RUNBOOK", "MATRIX", "SUMMARY", "REPORT", "DOCS",
    "THE", "AND", "OR", "NOT", "IN", "ON", "TO", "FOR", "BY", "AT", "AS", "IS", "OF",
    "CI", "CD", "PR", "QA", "UAT", "E2E",
    "VG", "GSD", "RTB", "SSP", "DSP",  # project abbreviations
    "PM2", "NPM", "YARN", "PNPM", "NODE",
    "IAB", "CPM", "CPC", "CTR",  # ad industry abbreviations
}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_phase_id(dir_name: str) -> str:
    """'07.12-conversion-tracking-pixel' → '7.12'"""
    m = re.match(r"^0?(\d+(?:\.\d+)*)", dir_name)
    return m.group(1) if m else dir_name


def list_phases() -> list[Path]:
    """Return sorted list of phase dirs."""
    if not PHASES_DIR.exists():
        return []
    phases = [p for p in PHASES_DIR.iterdir() if p.is_dir()]
    phases.sort(key=lambda p: normalize_phase_id(p.name))
    return phases


def infer_services(phase_dir: Path) -> list[str]:
    """Infer services this phase touches from SPECS + CONTEXT + name."""
    services = set()
    name_lower = phase_dir.name.lower()

    # Check phase name first
    for svc, patterns in SERVICE_HINTS:
        for pat in patterns:
            if re.search(pat, name_lower, re.I):
                services.add(svc)
                break

    # Deep-scan SPECS + CONTEXT for more service hints
    for fname in ("SPECS.md", "CONTEXT.md"):
        f = phase_dir / fname
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for svc, patterns in SERVICE_HINTS:
            for pat in patterns:
                if re.search(pat, text, re.I):
                    services.add(svc)
                    break

    return sorted(services) if services else ["(chưa xác định)"]


def extract_lessons_from_runbook(runbook_path: Path) -> list[str]:
    """Parse section 5 (Lessons) of a canonical runbook."""
    if not runbook_path.exists():
        return []
    text = runbook_path.read_text(encoding="utf-8", errors="ignore")
    # Section 5 starts with `## 5. Lessons` header, ends before next `##`
    m = re.search(r"^## 5\. Lessons.*?\n(.*?)(?=^## \d+\. |\Z)", text, re.M | re.S)
    if not m:
        return []
    body = m.group(1)
    # Extract bullet items (user + auto-detected)
    bullets = [b.strip() for b in re.findall(r"^[-*]\s+(.+)$", body, re.M)]
    # Filter placeholder text
    bullets = [b for b in bullets if "LESSONS_USER_INPUT_PENDING" not in b
               and not b.startswith("_(")
               and len(b) > 10]
    return bullets


def extract_env_vars(phase_dir: Path) -> list[dict]:
    """Grep SPECS + CONTEXT for env var candidates; enrich with heuristic purpose.

    Strict heuristic (v1.14.0 step 8 — reduce false positives):
      - Name MUST contain `_` (rejects ACTUALLY, COMPLETELY, STATUS-like noise)
      - OR name must have a visible sample value (`NAME=value` / `NAME: value`)
      - OR name appears inside backticks (`NAME`) in prose or code
    """
    results = []
    seen_names = set()

    for fname in ("SPECS.md", "CONTEXT.md", "PLAN.md"):
        f = phase_dir / fname
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")

        for m in ENV_VAR_RE.finditer(text):
            name = m.group(1)
            if name in ENV_BLOCKLIST:
                continue
            if name in seen_names:
                continue

            # Context around mention
            start = max(0, m.start() - 50)
            end = min(len(text), m.end() + 80)
            snippet = re.sub(r"\s+", " ", text[start:end]).strip()

            # Extract sample value
            sample = ""
            sm = re.search(rf"\b{re.escape(name)}\s*[=:]\s*([^\s\n|}}]+)", snippet)
            if sm:
                sample = sm.group(1).strip("`'\",;").strip()[:30]

            # Backtick check — is the name inside `...` in the source?
            in_backticks = bool(re.search(rf"`[^`]*\b{re.escape(name)}\b[^`]*`", text))

            # STRICT heuristic (v1.14.0 step 8 — kill false positives):
            # Accept ONLY IF:
            #   (a) name has underscore AND (has sample OR has env-var suffix OR prefix), OR
            #   (b) name is in backticks AND has sample value
            # Reject emphasis words (ACTUALLY, ALREADY, ALWAYS, APPROXIMATION) —
            # all caps single English words don't satisfy (a) or (b).
            has_underscore = "_" in name
            env_prefixes = ("NODE_", "VG_", "VOLLX_", "DB_", "REDIS_", "MONGO_",
                           "PG_", "POSTGRES_", "KAFKA_", "CLICKHOUSE_", "RTB_",
                           "SSP_", "DSP_", "API_", "APP_", "WEB_", "PIXEL_",
                           "AWS_", "GCP_", "STRIPE_", "SENDGRID_", "CF_",
                           "NEXT_", "JWT_", "SESSION_", "CORS_", "HTTP_")
            env_suffixes = ("_URL", "_TOKEN", "_SECRET", "_KEY", "_HOST",
                           "_PORT", "_USER", "_PASS", "_PASSWORD", "_ID",
                           "_ENABLED", "_DISABLED", "_TTL", "_TIMEOUT",
                           "_PATH", "_DIR", "_FILE", "_ENV", "_MODE",
                           "_API", "_URI", "_ENDPOINT", "_CACHE",
                           "_DSN", "_DB", "_DATABASE", "_NAME",
                           "_ORIGINS", "_HOSTNAME", "_REGION", "_BUCKET")
            has_env_prefix = any(name.startswith(p) for p in env_prefixes)
            has_env_suffix = any(name.endswith(s) for s in env_suffixes)

            # Underscore bắt buộc — single-word ALL-CAPS là emphasis prose,
            # không phải env var (ACTUALLY, ALREADY, CRITICAL, CLAMPING, ...).
            if not has_underscore:
                continue

            # Sample value phải "trông giống value" — không phải chỉ 1 từ bình thường.
            # Env var thực có sample: URL, số, path, JSON, boolean, hoặc `${...}`.
            def looks_like_value(s: str) -> bool:
                if not s:
                    return False
                if len(s) > 30:
                    return False
                # Strong signals: có special chars hoặc số hoặc URL
                return bool(re.search(r"[/=\[\]{}:;.`\"']", s)
                           or re.match(r"^\d", s)
                           or re.match(r"^(true|false|null|on|off|yes|no)$", s, re.I)
                           or "_" in s
                           or s.startswith("$"))

            has_real_sample = looks_like_value(sample) if sample else False

            # Signal thứ 2: env prefix/suffix (VD VG_, NODE_, _URL, _TOKEN)
            has_env_signal = has_env_prefix or has_env_suffix

            # Candidate nếu: real sample HOẶC env signal
            if not (has_real_sample or has_env_signal):
                continue

            seen_names.add(name)

            purpose = snippet[:100]
            if len(snippet) > 100:
                purpose = purpose + "..."

            results.append({
                "name":    name,
                "sample":  sample or "(not-in-spec)",
                "purpose": purpose,
                "source":  fname,
            })

    return results


def write_deploy_lessons(phases: list[Path]) -> Path:
    """View A + View B + View C → .vg/DEPLOY-LESSONS.md."""
    out = [
        "# Deploy Lessons — Aggregated",
        "",
        f"**Generated:** {iso_now()}",
        f"**Source:** {len(phases)} phases trong `.vg/phases/`",
        "",
        "3 views:",
        "- **View A — By Service**: lessons nhóm theo app/infra.",
        "- **View B — By Topic**: cross-cut theme (timing, env, migration, failure).",
        "- **View C — Service Dependency Graph (ASCII)**: startup order, edges, restart sequence.",
        "",
        "---",
        "",
    ]

    # ━━ VIEW A — By Service ━━
    out.append("## View A — By Service (Bài học theo dịch vụ)")
    out.append("")

    lessons_by_service: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for p in phases:
        services = infer_services(p)
        lessons = extract_lessons_from_runbook(p / "DEPLOY-RUNBOOK.md")
        pid = normalize_phase_id(p.name)
        for svc in services:
            for lesson in lessons:
                lessons_by_service[svc].append((pid, lesson))

    if not lessons_by_service:
        out.append("_(Chưa có phase nào có `DEPLOY-RUNBOOK.md` canonical với section 5 Lessons điền. Aggregator sẽ populate khi phase đầu tiên hoàn tất /vg:accept với v1.14.0+ flow.)_")
        out.append("")
    else:
        for svc in sorted(lessons_by_service.keys()):
            out.append(f"### {svc}")
            out.append("")
            for pid, lesson in lessons_by_service[svc]:
                out.append(f"- **Phase {pid}:** {lesson}")
            out.append("")

    # ━━ VIEW B — By Topic ━━
    out.append("## View B — By Topic (Bài học theo chủ đề cross-cut)")
    out.append("")

    out.append("### Build timing")
    out.append("_(Sync từ `.vg/DEPLOY-PERF-BASELINE.md` — aggregator extras, step 9.)_")
    out.append("")

    out.append("### Env vars introduced")
    out.append("_(Sync từ `.vg/ENV-CATALOG.md` — cùng aggregator.)_")
    out.append("")

    out.append("### Migration gotchas")
    out.append("")
    migration_phases = [p for p in phases
                       if re.search(r"migration|migrate|schema|additive", p.name, re.I)
                       or (p / "SPECS.md").exists()
                       and re.search(r"migration|schema\s+change|partition|drop\s+column|alter\s+table",
                                     (p / "SPECS.md").read_text(encoding="utf-8", errors="ignore"), re.I)]
    if migration_phases:
        for p in migration_phases:
            pid = normalize_phase_id(p.name)
            out.append(f"- **Phase {pid}** (`{p.name}`): xem runbook section 4 Rollback cho chi tiết.")
    else:
        out.append("_(Chưa có phase migration nào detect được.)_")
    out.append("")

    out.append("### Failure patterns (top recurring)")
    out.append("_(Sync từ `.vg/DEPLOY-FAILURE-REGISTER.md` — aggregator extras, step 9.)_")
    out.append("")

    # ━━ VIEW C — Dependency graph ASCII ━━
    out.append("## View C — Service Dependency Graph (ASCII, grep-friendly)")
    out.append("")
    out.append("```")
    out.append("# startup order (top-down; parallels at same line ok)")
    out.append("mongodb ─┐")
    out.append("redis   ─┤")
    out.append("kafka   ─┼──> api ──> workers ──> pixel(optional)")
    out.append("clickh. ─┘         ├──> web")
    out.append("                   └──> admin")
    out.append("")
    out.append("# edges (service → depends_on)")
    out.append("api       -> mongodb, redis")
    out.append("workers   -> api, kafka, clickhouse")
    out.append("web       -> api")
    out.append("admin     -> api")
    out.append("pixel     -> api                  # optional, only if pixel phase deployed")
    out.append("rtb-engine-> redis, kafka         # auction hot-path")
    out.append("")
    out.append("# restart order (full cycle, e.g. after infra change)")
    out.append("1. mongodb, redis, kafka, clickhouse   (infra tier — parallel ok)")
    out.append("2. api                                  (wait for #1 health)")
    out.append("3. workers, rtb-engine                  (wait for #2 + kafka topics exist)")
    out.append("4. web, admin, pixel                    (wait for #2, parallel ok)")
    out.append("```")
    out.append("")
    out.append("_Grep-friendly: `grep -A 2 '^api' .vg/DEPLOY-LESSONS.md` → show api + 2 lines dưới._")
    out.append("")
    out.append("_Cách chỉnh (v1.14.0+): edit trực tiếp code fence ở trên. Aggregator preserve nếu template match signature._")
    out.append("")

    path = VG_ROOT / "DEPLOY-LESSONS.md"
    VG_ROOT.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def write_env_catalog(phases: list[Path]) -> Path:
    """ENV-CATALOG.md — 8 cols."""
    out = [
        "# Env Catalog — Aggregated",
        "",
        f"**Generated:** {iso_now()}",
        f"**Source:** SPECS.md + CONTEXT.md + PLAN.md của {len(phases)} phases",
        "",
        "Mỗi env var được scan heuristic từ phase artifacts. Cột Purpose/Reload/Rotation/Storage cần user bổ sung — aggregator chỉ suggest nếu có hints.",
        "",
        "| Name | Added Phase | Service | Sample Value | Purpose | Reload | Rotation | Storage |",
        "|---|---|---|---|---|---|---|---|",
    ]

    # Gather all env vars, keep first-seen phase
    env_rows = {}  # name -> row
    for p in phases:
        pid = normalize_phase_id(p.name)
        services = infer_services(p)
        service_str = ", ".join(services[:2])  # top 2 services
        for ev in extract_env_vars(p):
            name = ev["name"]
            if name in env_rows:
                continue  # keep first-seen
            # Heuristic reload/rotation/storage
            reload_hint = "restart"
            rotation_hint = "manual-review"
            storage_hint = ".env"
            if "SECRET" in name or "TOKEN" in name or "PASSWORD" in name or "KEY" in name:
                rotation_hint = "90-day"
                storage_hint = "vault"
            if "URL" in name or "ENDPOINT" in name:
                rotation_hint = "config-stable"
            if "TTL" in name or "CACHE" in name or "TIMEOUT" in name:
                reload_hint = "hot-reload"
                rotation_hint = "tuning-knob"

            env_rows[name] = {
                "name":    name,
                "phase":   pid,
                "service": service_str,
                "sample":  ev["sample"],
                "purpose": ev["purpose"][:80],
                "reload":  reload_hint,
                "rotation": rotation_hint,
                "storage": storage_hint,
            }

    if not env_rows:
        out.append("| _(Không phát hiện env var nào qua heuristic scan — workflow chưa ghi env vars ở định dạng nhận diện được)_ | | | | | | | |")
    else:
        for name in sorted(env_rows.keys()):
            r = env_rows[name]
            purpose_esc = r["purpose"].replace("|", "\\|")
            out.append(f"| `{r['name']}` | {r['phase']} | {r['service']} | `{r['sample']}` "
                       f"| {purpose_esc} | {r['reload']} | {r['rotation']} | {r['storage']} |")

    out.append("")
    out.append("## Quy ước cột")
    out.append("")
    out.append("- **Reload**: `restart` (pm2 reload) / `hot-reload` (signal hoặc config watcher) / `config-stable` (rare change).")
    out.append("- **Rotation**: `90-day` (secrets) / `config-stable` (URLs/endpoints) / `tuning-knob` (perf knobs) / `manual-review`.")
    out.append("- **Storage**: `.env` (gitignored) / `env.j2` (Ansible template) / `vault` (secret manager).")
    out.append("")
    out.append(f"_Entries: {len(env_rows)} env vars scanned từ {len(phases)} phases._")
    out.append("")

    path = VG_ROOT / "ENV-CATALOG.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


# ═══════════════════════════════════════════════════════════════════════════
# Step 9 (C.4b extras) — 4 additional aggregators
# ═══════════════════════════════════════════════════════════════════════════


def parse_log_entries(log_path: Path) -> list[dict]:
    """Parse `.deploy-log.txt` BEGIN/END/STDOUT_LAST_LINES blocks.

    Duplicate of vg_deploy_runbook_drafter parser to keep aggregator self-contained.
    """
    if not log_path.exists():
        return []

    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    begin_re = re.compile(r"^\[([^\]]+)\] \[([^\]]+)\] BEGIN (.+)$")
    end_re   = re.compile(r"^\[([^\]]+)\] \[([^\]]+)\] END rc=(-?\d+) duration=(\d+)s")
    stout_re = re.compile(r"^\[([^\]]+)\] \[([^\]]+)\] STDOUT_LAST_LINES:")
    line_re  = re.compile(r"^  → (.+)$")

    entries = []
    pending: dict | None = None
    collecting_stdout = False

    for line in lines:
        bm = begin_re.match(line)
        em = end_re.match(line)
        sm = stout_re.match(line)
        lm = line_re.match(line)

        if bm:
            if pending and "rc" in pending:
                entries.append(pending)
            pending = {
                "begin_ts": bm.group(1),
                "tag":      bm.group(2),
                "cmd":      bm.group(3),
                "stdout_tail": [],
            }
            collecting_stdout = False
        elif em and pending:
            pending["end_ts"]   = em.group(1)
            pending["rc"]       = int(em.group(3))
            pending["duration"] = int(em.group(4))
        elif sm and pending:
            collecting_stdout = True
        elif lm and pending and collecting_stdout:
            pending["stdout_tail"].append(lm.group(1))

    if pending and "rc" in pending:
        entries.append(pending)
    return entries


def _error_signature(entry: dict) -> str:
    """Distill a short error signature từ stdout_tail hoặc cmd."""
    tail = entry.get("stdout_tail") or []
    for line in tail:
        # Common error patterns
        if re.search(r"(error|fail|exception|denied|refused|timeout|not found|EADDRINUSE|ENOENT)",
                     line, re.I):
            return line[:100]
    # Fallback: first word of cmd
    return f"rc={entry.get('rc', '?')} @ {entry.get('cmd', '')[:50]}"


def write_failure_register(phases: list[Path]) -> Path:
    """DEPLOY-FAILURE-REGISTER.md — chronological failure ledger."""
    out = [
        "# Deploy Failure Register — Chronological",
        "",
        f"**Generated:** {iso_now()}",
        f"**Source:** rc != 0 entries từ `.deploy-log.txt` của {len(phases)} phases",
        "",
        "Mỗi row = 1 lần deploy fail. Dùng để detect pattern lặp (recurrence guard).",
        "",
        "| Date | Phase | Tag/Service | Error Signature | Command | Duration | Root Cause | Fix Applied | Recurrence Guard |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    rows = []
    for p in phases:
        pid = normalize_phase_id(p.name)
        log = p / ".deploy-log.txt"
        entries = parse_log_entries(log)
        for e in entries:
            if e.get("rc", 0) == 0:
                continue
            date = e.get("begin_ts", "?").split("T")[0]
            sig = _error_signature(e)
            cmd_short = e.get("cmd", "")[:50].replace("|", "\\|")
            sig_esc = sig.replace("|", "\\|")
            rows.append({
                "date": date,
                "phase": pid,
                "tag": e.get("tag", "?"),
                "sig": sig_esc,
                "cmd": cmd_short,
                "duration": e.get("duration", 0),
            })

    # Sort chronologically
    rows.sort(key=lambda r: (r["date"], r["phase"]))

    if not rows:
        out.append("| _(Chưa có failure nào — hoặc phase chưa chạy qua deploy-logging mode)_ | | | | | | | | |")
    else:
        for r in rows:
            out.append(f"| {r['date']} | {r['phase']} | {r['tag']} "
                       f"| {r['sig']} | `{r['cmd']}` | {r['duration']}s "
                       f"| _(user điền)_ | _(user điền)_ | _(user điền)_ |")

    out.append("")
    out.append("## Recurring signatures (top patterns)")
    out.append("")
    if rows:
        # Group by signature first 50 chars
        sig_counts: dict[str, int] = defaultdict(int)
        for r in rows:
            sig_counts[r["sig"][:50]] += 1
        top = sorted(sig_counts.items(), key=lambda x: -x[1])[:10]
        top = [(s, c) for s, c in top if c > 1]
        if top:
            for sig, cnt in top:
                out.append(f"- **{cnt}×** `{sig}`")
        else:
            out.append("_(Không có signature nào lặp >1 lần.)_")
    else:
        out.append("_(N/A — chưa có failure nào.)_")
    out.append("")

    path = VG_ROOT / "DEPLOY-FAILURE-REGISTER.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def write_deploy_recipes(phases: list[Path]) -> Path:
    """DEPLOY-RECIPES.md — copy-paste cookbook synthesized từ RUNBOOK sections 3+4."""
    out = [
        "# Deploy Recipes — Copy-paste Cookbook",
        "",
        f"**Generated:** {iso_now()}",
        f"**Source:** RUNBOOK sections 3 (Verification) + 4 (Rollback) của {len(phases)} phases",
        "",
        "Quick snippets dùng ngay; không cần mở RUNBOOK từng phase.",
        "",
    ]

    restart_cmds = set()
    tail_cmds = set()
    smoke_cmds = set()
    rollback_cmds = set()

    for p in phases:
        runbook = p / "DEPLOY-RUNBOOK.md"
        log = p / ".deploy-log.txt"

        # Extract commands from log if canonical runbook missing
        source_entries = []
        if log.exists():
            source_entries = parse_log_entries(log)

        for e in source_entries:
            cmd = e.get("cmd", "").strip()
            tag = e.get("tag", "").lower()

            if not cmd or e.get("rc", 0) != 0:
                continue

            if "reload" in cmd or "restart" in cmd:
                restart_cmds.add(cmd)
            elif "logs" in cmd or "tail" in cmd:
                tail_cmds.add(cmd)
            elif tag == "health" or "health" in cmd.lower() or "/health" in cmd:
                smoke_cmds.add(cmd)
            elif tag == "rollback" or "revert" in cmd or "rollback" in cmd.lower():
                rollback_cmds.add(cmd)

    def _block(title: str, cmds: set) -> list[str]:
        lines = [f"## {title}", ""]
        if cmds:
            lines.append("```bash")
            for c in sorted(cmds):
                lines.append(c)
            lines.append("```")
        else:
            lines.append(f"_(Chưa có lệnh `{title.lower()}` nào trong logs. Phase wire deploy-logging → sẽ populate tự động.)_")
        lines.append("")
        return lines

    out.extend(_block("Restart services", restart_cmds))
    out.extend(_block("Tail logs", tail_cmds))
    out.extend(_block("Verify deployment (smoke)", smoke_cmds))
    out.extend(_block("Rollback", rollback_cmds))

    # Generic helpers (always useful)
    # Note: SSH alias + project path emitted from vg.config.md (environments.sandbox.*).
    # Read at template-emit time so the generated DEPLOY-RECIPES.md reflects current
    # config — never hardcode "ssh vollx" or "/home/vollx/vollxssp" in template strings.
    ssh_alias, project_path = _load_sandbox_runtime_keys()
    out.append("## Generic helpers")
    out.append("")
    out.append("```bash")
    out.append("# Full smoke pack (placeholder — step 18 wires .claude/scripts/vg_smoke_pack.sh):")
    out.append("# bash .claude/scripts/vg_smoke_pack.sh sandbox")
    out.append("")
    out.append(f"# PM2 status on {ssh_alias}:")
    out.append(f"ssh {ssh_alias} 'pm2 jlist | jq -r \".[] | [.name, .pm2_env.status, .pm2_env.restart_time] | @tsv\"'")
    out.append("")
    out.append("# Disk pressure check:")
    out.append(f"ssh {ssh_alias} 'df -h / && du -sh {project_path}'")
    out.append("```")
    out.append("")

    path = VG_ROOT / "DEPLOY-RECIPES.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def write_perf_baseline(phases: list[Path]) -> Path:
    """DEPLOY-PERF-BASELINE.md — timing trends per phase."""
    out = [
        "# Deploy Perf Baseline — Timing Trends",
        "",
        f"**Generated:** {iso_now()}",
        f"**Source:** duration (s) từ `.deploy-log.txt` theo tag, {len(phases)} phases",
        "",
        "Regression alert: phase N timing > 1.5× median(last 3 phases) → flag vào RUNBOOK section 5 (Lessons).",
        "",
        "| Phase | Build (s) | Restart (s) | Health-ready (s) | Total (s) | Flag |",
        "|---|---|---|---|---|---|",
    ]

    phase_timings = []
    for p in phases:
        log = p / ".deploy-log.txt"
        if not log.exists():
            continue
        entries = parse_log_entries(log)
        if not entries:
            continue

        build_t = sum(e["duration"] for e in entries
                     if "build" in e.get("tag", "").lower() or "build" in e.get("cmd", "").lower())
        restart_t = sum(e["duration"] for e in entries
                       if "restart" in e.get("tag", "").lower() or "reload" in e.get("cmd", "").lower())
        health_t = sum(e["duration"] for e in entries
                      if e.get("tag", "") == "health" or "/health" in e.get("cmd", ""))
        total_t = sum(e["duration"] for e in entries)

        phase_timings.append({
            "phase":   normalize_phase_id(p.name),
            "build":   build_t,
            "restart": restart_t,
            "health":  health_t,
            "total":   total_t,
        })

    # Regression check: compare each phase to rolling median of last 3
    def _flag(pt: dict, prev3: list[dict]) -> str:
        if len(prev3) < 3:
            return ""
        for key in ("build", "restart", "total"):
            vals = sorted(p[key] for p in prev3 if p[key] > 0)
            if not vals:
                continue
            median = vals[len(vals) // 2]
            if pt[key] > median * 1.5 and median > 0:
                return f"\033[33m{key} slow 1.5×\033[0m"
        return "✅"

    if not phase_timings:
        out.append("| _(Chưa có phase nào có `.deploy-log.txt`)_ | | | | | |")
    else:
        for i, pt in enumerate(phase_timings):
            prev3 = phase_timings[max(0, i - 3):i]
            flag = _flag(pt, prev3)
            out.append(f"| {pt['phase']} | {pt['build']} | {pt['restart']} "
                       f"| {pt['health']} | {pt['total']} | {flag} |")

    out.append("")
    out.append("## Rolling trends")
    out.append("")
    if len(phase_timings) >= 3:
        recent = phase_timings[-5:]
        avg_total = sum(p["total"] for p in recent) / len(recent)
        out.append(f"- Last {len(recent)} phases avg total deploy time: **{avg_total:.0f}s**")
        avg_build = sum(p["build"] for p in recent if p["build"] > 0)
        if avg_build:
            out.append(f"- Last {len(recent)} phases build time sum: **{avg_build}s** "
                       f"(avg/phase: {avg_build // len(recent)}s)")
    else:
        out.append("_(Cần ≥3 phases để compute trend — hiện có ít hơn.)_")
    out.append("")

    path = VG_ROOT / "DEPLOY-PERF-BASELINE.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def write_smoke_pack(phases: list[Path]) -> Path:
    """SMOKE-PACK.md — reusable smoke snippets per service, tagged by added phase."""
    out = [
        "# Smoke Pack — Reusable Health/Smoke Snippets",
        "",
        f"**Generated:** {iso_now()}",
        f"**Source:** health-tagged commands từ logs + runbook section 3, {len(phases)} phases",
        "",
        "Dùng cho: `/vg:review` preflight, `/vg:regression`, RUNBOOK section 3 auto-populate.",
        "",
        "Consumed bởi: `bash .claude/scripts/vg_smoke_pack.sh {env}` (runner tương lai, step 18).",
        "",
    ]

    # Group smoke commands by service heuristic
    smoke_by_service: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for p in phases:
        pid = normalize_phase_id(p.name)
        log = p / ".deploy-log.txt"
        if not log.exists():
            continue
        entries = parse_log_entries(log)
        for e in entries:
            cmd = e.get("cmd", "").strip()
            tag = e.get("tag", "").lower()
            if not cmd:
                continue
            # Is this a smoke/health check?
            is_smoke = (tag == "health"
                       or "/health" in cmd.lower()
                       or (re.search(r"curl\s+-s", cmd) and "health" in cmd.lower()))
            if not is_smoke:
                continue

            # Infer service from cmd hostname/endpoint
            svc = "generic"
            for pattern, service in [
                (r"api\.", "api"),
                (r"admin\.", "admin"),
                (r"dsp\.", "dsp"),
                (r"rtb\.", "rtb-engine"),
                (r"sdk\.", "sdk"),
                (r"pixel\.", "pixel"),
                (r":3001", "api"),
                (r":3002", "pixel"),
                (r":3000", "web"),
            ]:
                if re.search(pattern, cmd, re.I):
                    svc = service
                    break

            smoke_by_service[svc].append((pid, cmd))

    if not smoke_by_service:
        out.append("_(Chưa có smoke command nào trong logs. Phase chưa wire `deploy_exec \"health\" \"...\"` → sẽ populate khi build/test sandbox flow update.)_")
        out.append("")
        out.append("## Starter templates (manually curated)")
        out.append("")
        out.append("### api")
        out.append("```bash")
        # INTENTIONAL_HARDCODE: starter-template literals (admin curates DEPLOY-RECIPES — Phase K1 register §4)
        out.append("curl -sf http://localhost:3001/health && echo OK")
        out.append("curl -sf https://api.vollx.com/health && echo OK")
        out.append("```")
        out.append("")
        out.append("### web")
        out.append("```bash")
        out.append("curl -sf https://ssp.vollx.com/ | head -c 200")
        out.append("curl -sf https://admin.vollx.com/ | head -c 200")
        out.append("```")
        out.append("")
        out.append("### pixel (Phase 7.12+)")
        out.append("```bash")
        out.append("curl -sf https://pixel.vollx.com/health")
        out.append("curl -sfI https://pixel.vollx.com/p.gif?e=test | head -1")
        out.append("```")
    else:
        for svc in sorted(smoke_by_service.keys()):
            out.append(f"## {svc}")
            out.append("")
            out.append("```bash")
            seen_cmds = set()
            for pid, cmd in smoke_by_service[svc]:
                if cmd in seen_cmds:
                    continue
                seen_cmds.add(cmd)
                out.append(f"# Added phase {pid}")
                out.append(cmd)
            out.append("```")
            out.append("")

    out.append("## Run all smoke pack")
    out.append("")
    out.append("```bash")
    out.append("# (step 18 sẽ sinh wrapper .claude/scripts/vg_smoke_pack.sh)")
    out.append("# Example call — runner execute mỗi block, exit 0 nếu tất cả green:")
    out.append("# bash .claude/scripts/vg_smoke_pack.sh sandbox")
    out.append("```")
    out.append("")

    path = VG_ROOT / "SMOKE-PACK.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Aggregate deploy RUNBOOKs → project-wide lessons + catalogs")
    p.add_argument("--outputs", nargs="*",
                   default=["deploy-lessons", "env-catalog",
                           "failure-register", "deploy-recipes",
                           "perf-baseline", "smoke-pack"],
                   choices=["deploy-lessons", "env-catalog",
                           "failure-register", "deploy-recipes",
                           "perf-baseline", "smoke-pack"],
                   help="Which aggregate outputs to write (default: all 6)")
    p.add_argument("--vg-root", default=".vg",
                   help="VG root directory (default: .vg)")
    args = p.parse_args(argv)

    global VG_ROOT, PHASES_DIR
    VG_ROOT = Path(args.vg_root)
    PHASES_DIR = VG_ROOT / "phases"

    phases = list_phases()
    print(f"▸ Found {len(phases)} phase dirs trong {PHASES_DIR}")

    written = []
    writers = [
        ("deploy-lessons",   write_deploy_lessons),
        ("env-catalog",      write_env_catalog),
        ("failure-register", write_failure_register),
        ("deploy-recipes",   write_deploy_recipes),
        ("perf-baseline",    write_perf_baseline),
        ("smoke-pack",       write_smoke_pack),
    ]
    for key, fn in writers:
        if key in args.outputs:
            path = fn(phases)
            written.append(path)
            print(f"  ✓ {path}")

    print(f"\nAggregation done. Wrote {len(written)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
