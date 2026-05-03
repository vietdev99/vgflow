<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 13: Integration golden fixture + end-to-end test

**Files:**
- Create: `tests/fixtures/build-fix-loop-golden/`
- Create: `tests/test_build_fix_loop_integration.py`

- [ ] **Step 1: Create golden fixture (synthetic phase with FE→BE gap)**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
mkdir -p tests/fixtures/build-fix-loop-golden/phase/{PLAN,API-CONTRACTS,BUILD-LOG,fe,be}
```

Create `tests/fixtures/build-fix-loop-golden/phase/PLAN/task-39.md`:
```markdown
# task-39

File: tests/fixtures/build-fix-loop-golden/phase/be/router.ts
File: tests/fixtures/build-fix-loop-golden/phase/fe/InvoiceDetailPage.tsx
```

Create `tests/fixtures/build-fix-loop-golden/phase/API-CONTRACTS/post-api-invoices-payments.md`:
```markdown
# POST /api/v1/admin/invoices/:id/payments

**Method:** POST
**Path:** /api/v1/admin/invoices/:id/payments
**Response 201:** { "id": "string" }
```

Create `tests/fixtures/build-fix-loop-golden/phase/be/router.ts`:
```typescript
import { Router } from 'express';
const r = Router();
r.post('/api/v1/admin/invoices/:id/payments', handler);
export default r;
```

Create `tests/fixtures/build-fix-loop-golden/phase/fe/InvoiceDetailPage.tsx`:
```typescript
import axios from 'axios';
export function InvoiceDetailPage({ id }: { id: string }) {
  // BUG: GET endpoint does not exist on BE
  axios.get('/api/v1/admin/invoices/' + id + '/payments');
  return null;
}
```

Create `tests/fixtures/build-fix-loop-golden/phase/BUILD-LOG/task-39.md`:
```markdown
# task-39 build log

POST /api/v1/admin/invoices/:id/payments returns 201 (sync, with id field).
```

- [ ] **Step 2: Write the integration test**

Create `tests/test_build_fix_loop_integration.py`:

```python
"""End-to-end: golden fixture phase produces expected L4a-i + L4a-ii results."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "build-fix-loop-golden" / "phase"


def test_l4a_i_detects_fe_be_gap(tmp_path: Path) -> None:
    out = tmp_path / "ev.json"
    result = subprocess.run([
        "python3", str(REPO / "scripts" / "validators" / "verify-fe-be-call-graph.py"),
        "--fe-root", str(FIXTURE / "fe"),
        "--be-root", str(FIXTURE / "be"),
        "--phase", "golden-test",
        "--evidence-out", str(out),
    ], capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["category"] == "fe_be_call_graph"
    assert "GET" in ev["summary"]


def test_classifier_marks_gap_in_scope(tmp_path: Path) -> None:
    """Run L4a-i, then feed evidence into classifier — expect IN_SCOPE."""
    ev_path = tmp_path / "ev.json"
    subprocess.run([
        "python3", str(REPO / "scripts" / "validators" / "verify-fe-be-call-graph.py"),
        "--fe-root", str(FIXTURE / "fe"),
        "--be-root", str(FIXTURE / "be"),
        "--phase", "golden-test",
        "--evidence-out", str(ev_path),
    ], capture_output=True, text=True)

    cls = subprocess.run([
        "python3", str(REPO / "scripts" / "classify-build-warning.py"),
        "--phase-dir", str(FIXTURE),
        "--warning", str(ev_path),
    ], capture_output=True, text=True, check=False)
    assert cls.returncode == 0, cls.stderr
    out = json.loads(cls.stdout)
    # Fixture: FE file path appears in PLAN/task-39.md → R3 hit → IN_SCOPE
    assert out["classification"] == "IN_SCOPE"


def test_phase_ownership_excludes_outside_files() -> None:
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from phase_ownership import is_owned  # type: ignore

    assert is_owned("tests/fixtures/build-fix-loop-golden/phase/be/router.ts", FIXTURE)
    assert not is_owned("apps/api/src/middleware/error.ts", FIXTURE)
    sys.path.remove(str(REPO / "scripts" / "lib"))
```

- [ ] **Step 3: Run the integration test**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_build_fix_loop_integration.py -v
```
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/build-fix-loop-golden/ tests/test_build_fix_loop_integration.py
git commit -m "test(build-fix-loop): add golden fixture + L4a-i + classifier + ownership E2E"
```

---

