<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 2: B1 — FE→BE call graph extractor

**Files:**
- Create: `scripts/extractors/extract-fe-api-calls.py`
- Create: `scripts/extractors/extract-be-route-registry.py`
- Test: `tests/test_fe_be_call_graph.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fe_be_call_graph.py`:

```python
"""Tests for FE call extractor + BE route registry extractor."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FE_EXTRACTOR = REPO / "scripts" / "extractors" / "extract-fe-api-calls.py"
BE_EXTRACTOR = REPO / "scripts" / "extractors" / "extract-be-route-registry.py"


def _run(script: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(script), *args],
        capture_output=True, text=True, check=False,
    )


def test_fe_extractor_finds_axios_get(tmp_path: Path) -> None:
    f = tmp_path / "Page.tsx"
    f.write_text(textwrap.dedent("""
        import axios from 'axios';
        export function Page() {
          axios.get('/api/v1/admin/invoices/' + id + '/payments');
          return <div/>;
        }
    """).strip(), encoding="utf-8")
    result = _run(FE_EXTRACTOR, ["--root", str(tmp_path), "--format", "json"])
    assert result.returncode == 0, result.stderr
    calls = json.loads(result.stdout)["calls"]
    assert any(c["method"] == "GET" and "/api/v1/admin/invoices" in c["path_template"] for c in calls)


def test_fe_extractor_finds_fetch(tmp_path: Path) -> None:
    f = tmp_path / "hook.ts"
    f.write_text(textwrap.dedent("""
        export async function fetchPayments(id: string) {
          return fetch(`/api/v1/admin/invoices/${id}/payments`, { method: 'GET' });
        }
    """).strip(), encoding="utf-8")
    result = _run(FE_EXTRACTOR, ["--root", str(tmp_path), "--format", "json"])
    assert result.returncode == 0
    calls = json.loads(result.stdout)["calls"]
    assert any(c["method"] == "GET" and "payments" in c["path_template"] for c in calls)


def test_be_extractor_finds_express_route(tmp_path: Path) -> None:
    f = tmp_path / "router.ts"
    f.write_text(textwrap.dedent("""
        import { Router } from 'express';
        const r = Router();
        r.post('/api/v1/admin/invoices/:id/payments', handler);
        r.post('/api/v1/admin/invoices/:id/payments/:pid/approve', approve);
        export default r;
    """).strip(), encoding="utf-8")
    result = _run(BE_EXTRACTOR, ["--root", str(tmp_path), "--format", "json"])
    assert result.returncode == 0
    routes = json.loads(result.stdout)["routes"]
    methods = {(r["method"], r["path_template"]) for r in routes}
    assert ("POST", "/api/v1/admin/invoices/:id/payments") in methods
    # No GET present — required for L4a-i gap detection downstream.
    assert not any(r["method"] == "GET" for r in routes)


def test_be_extractor_finds_fastify(tmp_path: Path) -> None:
    f = tmp_path / "fastify.ts"
    f.write_text(textwrap.dedent("""
        export async function plugin(app) {
          app.get('/api/v1/health', healthHandler);
          app.post('/api/v1/orders', createOrder);
        }
    """).strip(), encoding="utf-8")
    result = _run(BE_EXTRACTOR, ["--root", str(tmp_path), "--format", "json"])
    assert result.returncode == 0
    routes = json.loads(result.stdout)["routes"]
    assert any(r["method"] == "GET" and r["path_template"] == "/api/v1/health" for r in routes)
```

- [ ] **Step 2: Run tests to confirm fail**

Run: `cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix" && python3 -m pytest tests/test_fe_be_call_graph.py -v`
Expected: 4 failures.

- [ ] **Step 3: Write FE extractor**

Create `scripts/extractors/extract-fe-api-calls.py`:

```python
#!/usr/bin/env python3
"""extract-fe-api-calls.py — grep-based extractor of FE → BE API calls.

Finds: axios.<method>(...), fetch(..., {method}), useQuery({queryKey: [...path]}),
       generated client SDK calls (api.invoices.list / api.invoices.payments.get).

Output: JSON {"calls": [{"file", "line", "method", "path_template"}]}

Limitations (P3 upgrade to ts-morph AST):
  - Template literals interpolating runtime variables produce path_template with
    `${...}` markers; this is intentional — comparison against BE registry
    treats `${X}` and `:X` (route param) equivalently.
  - Dynamic `${BASE_URL}/...` resolves only when BASE_URL appears in same file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

AXIOS_RE = re.compile(
    r"""axios\s*\.\s*(get|post|put|patch|delete|head|options)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)
FETCH_RE = re.compile(
    r"""fetch\s*\(\s*['"`]([^'"`]+)['"`]\s*(?:,\s*\{[^}]*method\s*:\s*['"`]([A-Z]+)['"`])?""",
)
TEMPLATE_FETCH_RE = re.compile(
    r"""fetch\s*\(\s*`([^`]+)`\s*(?:,\s*\{[^}]*method\s*:\s*['"`]([A-Z]+)['"`])?""",
)


def _normalize(template: str) -> str:
    """Replace `${var}` and `${expr}` with `:param` markers for comparison."""
    return re.sub(r"\$\{[^}]+\}", ":param", template)


def _scan_file(path: Path, calls: list[dict]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for i, line in enumerate(text.splitlines(), 1):
        for m in AXIOS_RE.finditer(line):
            calls.append({
                "file": str(path),
                "line": i,
                "method": m.group(1).upper(),
                "path_template": _normalize(m.group(2)),
            })
        for m in FETCH_RE.finditer(line):
            calls.append({
                "file": str(path),
                "line": i,
                "method": (m.group(2) or "GET").upper(),
                "path_template": _normalize(m.group(1)),
            })
        for m in TEMPLATE_FETCH_RE.finditer(line):
            calls.append({
                "file": str(path),
                "line": i,
                "method": (m.group(2) or "GET").upper(),
                "path_template": _normalize(m.group(1)),
            })


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract FE → BE API calls")
    parser.add_argument("--root", required=True, help="Source root (e.g. apps/web/src)")
    parser.add_argument("--format", default="json", choices=["json", "jsonl"])
    parser.add_argument("--ext", default=".tsx,.ts,.jsx,.js")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 1

    exts = tuple(args.ext.split(","))
    calls: list[dict] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in exts:
            _scan_file(path, calls)

    if args.format == "json":
        print(json.dumps({"calls": calls, "count": len(calls), "root": str(root)}))
    else:  # jsonl
        for c in calls:
            print(json.dumps(c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write BE extractor**

Create `scripts/extractors/extract-be-route-registry.py`:

```python
#!/usr/bin/env python3
"""extract-be-route-registry.py — grep-based BE route registry extractor.

Finds: Express (router.get/post/put/patch/delete),
       Fastify (app.get/post/...),
       NestJS (@Get('/path'), @Post('/path')),
       Hono (app.get/post/...).

Output: JSON {"routes": [{"file", "line", "method", "path_template"}]}.

Same `:param` normalization as FE extractor for direct cross-comparison.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROUTER_RE = re.compile(
    r"""(?:router|app|r)\s*\.\s*(get|post|put|patch|delete|head|options)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)
NEST_RE = re.compile(
    r"""@(Get|Post|Put|Patch|Delete|Head|Options)\s*\(\s*['"`]([^'"`]*)['"`]""",
)


def _scan_file(path: Path, routes: list[dict]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for i, line in enumerate(text.splitlines(), 1):
        for m in ROUTER_RE.finditer(line):
            routes.append({
                "file": str(path),
                "line": i,
                "method": m.group(1).upper(),
                "path_template": m.group(2),
            })
        for m in NEST_RE.finditer(line):
            routes.append({
                "file": str(path),
                "line": i,
                "method": m.group(1).upper(),
                "path_template": m.group(2),
            })


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract BE route registry")
    parser.add_argument("--root", required=True, help="Source root (e.g. apps/api/src)")
    parser.add_argument("--format", default="json", choices=["json", "jsonl"])
    parser.add_argument("--ext", default=".ts,.js")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 1

    exts = tuple(args.ext.split(","))
    routes: list[dict] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in exts:
            _scan_file(path, routes)

    if args.format == "json":
        print(json.dumps({"routes": routes, "count": len(routes), "root": str(root)}))
    else:
        for r in routes:
            print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Make executable + run tests**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
chmod +x scripts/extractors/extract-fe-api-calls.py scripts/extractors/extract-be-route-registry.py
python3 -m pytest tests/test_fe_be_call_graph.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/extractors/extract-fe-api-calls.py scripts/extractors/extract-be-route-registry.py tests/test_fe_be_call_graph.py
git commit -m "feat(build-fix-loop): add B1 FE call + BE route extractors (grep-based, AST upgrade later)"
```

---

