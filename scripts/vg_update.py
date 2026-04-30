"""VG workflow update helper.

Handles version compare, SHA256 verify, 3-way merge, patches manifest,
GitHub releases query, and CLI subcommands (check / fetch / merge).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def compare_versions(a: str, b: str) -> int:
    """Return -1/0/+1 like strcmp. Unparseable -> -1 (force update offer)."""
    def parse(v):
        try:
            return tuple(int(x) for x in v.lstrip("v").split("."))
        except Exception:
            return None
    pa, pb = parse(a), parse(b)
    if pa is None:
        return -1
    if pb is None:
        return 1
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def verify_sha256(path, expected: str) -> bool:
    """Streaming SHA256 verify. Returns False if file missing or hash mismatch."""
    p = Path(path)
    if not p.exists():
        return False
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest() == expected.strip().lower()


@dataclass
class MergeResult:
    status: str  # "clean" | "conflict"
    content: str


def three_way_merge(ancestor, current, upstream) -> MergeResult:
    """3-way merge via `git merge-file -p`.

    Returns MergeResult(status, content). Content is the merged text
    (with conflict markers if status == "conflict").
    """
    ancestor = Path(ancestor)
    current = Path(current)
    upstream = Path(upstream)

    if not current.exists():
        # New file from upstream -> accept as clean
        content = upstream.read_text(encoding="utf-8") if upstream.exists() else ""
        return MergeResult("clean", content)

    if not upstream.exists():
        # Removed upstream -> keep user
        return MergeResult("clean", current.read_text(encoding="utf-8"))

    if not ancestor.exists():
        # Issue #30: prior implementation returned ("conflict", cur_text)
        # when ancestor missing AND current != upstream. The caller in
        # update.md step 6 then parked `.merged` (= local content) as
        # `.conflict` and never copied upstream over local. Result:
        # /vg:update reported "updated=N conflicts=M skipped=K" with a
        # success-shaped UI, while ALL bug fixes silently failed to land.
        # Reproduces every time vgflow-ancestor/v${INSTALLED}/{rel} stash
        # is missing or stale — common after a prior failed update or a
        # manual VGFLOW-VERSION bump.
        #
        # Resilient default: when ancestor missing, take UPSTREAM as
        # authoritative. Without a baseline, 3-way merge is impossible;
        # the user's intent in running /vg:update is "give me the new
        # version", so prefer upstream over local. New status string
        # "force-upstream" lets the caller log distinctly without
        # treating it as a conflict.
        cur_text = current.read_text(encoding="utf-8")
        up_text = upstream.read_text(encoding="utf-8")
        if cur_text == up_text:
            return MergeResult("clean", cur_text)
        return MergeResult("force-upstream", up_text)

    # git merge-file mutates the "current" file in place; copy to temp first.
    # Use binary mode to preserve line endings exactly (Windows text mode would
    # translate \n -> \r\n on write, causing false conflicts against LF files).
    tmp_path = None
    tf = tempfile.NamedTemporaryFile(mode="wb", suffix=".merge", delete=False)
    try:
        tf.write(current.read_bytes())
        tf.close()
        tmp_path = tf.name

        r = subprocess.run(
            ["git", "merge-file", "-p", tmp_path, str(ancestor), str(upstream)],
            capture_output=True,
            text=True,
            # v2.41.3 (Issue #53 Bug #1) — without explicit encoding, Python on
            # Windows defaults to locale.getpreferredencoding() = cp1252. UTF-8
            # bytes >= 0x80 (⛔ → 0xe2,0x9b,0x94 etc) either crash with
            # UnicodeDecodeError or silently mojibake-decode (e.g. "⛔" → "â›"").
            # write_text(...) downstream then re-encodes mojibake as UTF-8,
            # silently corrupting hundreds of files in a single update run.
            encoding="utf-8",
            errors="replace",
        )
        # Exit code: 0 = clean, N>0 = N conflicts, <0 = error
        status = "clean" if r.returncode == 0 else "conflict"
        # Defensive fallback for the rare crash case where stdout is None
        # (e.g. git merge-file aborted before writing) — treat as conflict
        # with empty body so caller's write_text doesn't TypeError.
        return MergeResult(status, r.stdout or "")
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass


class PatchesManifest:
    """JSON-backed manifest of parked conflict files.

    Schema:
      {
        "version": 1,
        "entries": [
          {"path": "commands/vg/build.md", "status": "conflict", "added": "ISO8601Z"}
        ]
      }
    """

    def __init__(self, path):
        self.path = Path(path)
        self._load()

    def _load(self):
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self._data = {"version": 1, "entries": []}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, rel_path: str, status: str):
        # Dedup: replace if path already present
        self._data["entries"] = [
            e for e in self._data["entries"] if e["path"] != rel_path
        ]
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        self._data["entries"].append(
            {"path": rel_path, "status": status, "added": ts}
        )
        self._save()

    def remove(self, rel_path: str):
        self._data["entries"] = [
            e for e in self._data["entries"] if e["path"] != rel_path
        ]
        self._save()

    def list(self):
        return list(self._data["entries"])


# ---- Task C5: fetch_latest_release -------------------------------------------

def fetch_latest_release(repo: str = "vietdev99/vgflow", timeout: int = 10) -> dict:
    """Query GitHub REST API for latest release.

    Returns:
      {version, tag, tarball_url, sha256_url, published_at}

    Raises RuntimeError on network error or missing tarball asset.
    """
    api = "https://api.github.com/repos/{}/releases/latest".format(repo)
    req = urllib.request.Request(
        api,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "vg-update/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError("Cannot reach GitHub API: {}".format(e))

    tag = data["tag_name"]
    version = tag.lstrip("v")
    tarball = None
    sha256 = None
    for a in data.get("assets", []):
        name = a.get("name", "")
        if name.endswith(".sha256"):
            sha256 = a
        elif name.endswith(".tar.gz"):
            tarball = a
    if not tarball:
        raise RuntimeError("Release {} has no .tar.gz asset".format(tag))

    return {
        "version": version,
        "tag": tag,
        "tarball_url": tarball["browser_download_url"],
        "sha256_url": sha256["browser_download_url"] if sha256 else None,
        "published_at": data.get("published_at"),
    }


# ---- Task C6: CLI ------------------------------------------------------------

def _download(url: str, dest: Path, timeout: int = 60):
    """Stream download with explicit timeout and User-Agent."""
    req = urllib.request.Request(url, headers={"User-Agent": "vg-update/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        with dest.open("wb") as f:
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)

def cmd_check(args):
    """Print current + latest version + state."""
    current = "0.0.0"
    vf = Path(".claude/VGFLOW-VERSION")
    if vf.exists():
        current = vf.read_text(encoding="utf-8").strip()
    try:
        info = fetch_latest_release(args.repo)
    except RuntimeError as e:
        print("offline: {}".format(e), file=sys.stderr)
        print("current={} latest=unknown state=unknown".format(current))
        return 1
    cmp = compare_versions(current, info["version"])
    if cmp == 0:
        state = "up-to-date"
    elif cmp < 0:
        state = "update-available"
    else:
        state = "ahead-of-release"
    print("current={} latest={} state={}".format(current, info["version"], state))
    return 0


def cmd_fetch(args):
    """Download tarball + SHA256 + extract to .vgflow-cache/{tag}/."""
    info = fetch_latest_release(args.repo)
    cache = Path(".vgflow-cache")
    cache.mkdir(exist_ok=True)
    tar = cache / "vgflow-{}.tar.gz".format(info["tag"])
    print("Downloading {}...".format(info["tarball_url"]))
    _download(info["tarball_url"], tar)

    if info["sha256_url"]:
        sha_file = cache / (tar.name + ".sha256")
        _download(info["sha256_url"], sha_file)
        expected = sha_file.read_text(encoding="utf-8").split()[0]
        if not verify_sha256(tar, expected):
            print("SHA256 mismatch for {}".format(tar), file=sys.stderr)
            try:
                tar.unlink()
            except OSError:
                pass
            return 2
        print("SHA256 verified.")
    else:
        print("No SHA256 file published -- skipping verify (less secure)")

    import tarfile
    extract_to = cache / info["tag"]
    if extract_to.exists():
        shutil.rmtree(extract_to)
    extract_to.mkdir()
    with tarfile.open(tar, "r:gz") as tf:
        extract_root = extract_to.resolve()
        for m in tf.getmembers():
            dest = (extract_to / m.name).resolve()
            try:
                dest.relative_to(extract_root)
            except ValueError:
                raise RuntimeError("Unsafe path in tarball: {}".format(m.name))
        tf.extractall(extract_to)
    print("Extracted to {}".format(extract_to))
    print("EXTRACTED={}/vgflow".format(extract_to))
    return 0


def cmd_merge(args):
    """3-way merge a single file and write merged content to --output.

    Exit codes:
      0 — clean merge or force-upstream (caller can move .merged → target)
      1 — conflict with markers (caller should park as .conflict)

    Status strings on stdout:
      "clean"          — true 3-way clean OR upstream==local (no-op)
      "force-upstream" — ancestor missing, took upstream verbatim (issue #30)
      "conflict"       — markers present, caller parks
    """
    res = three_way_merge(Path(args.ancestor), Path(args.current), Path(args.upstream))
    Path(args.output).write_text(res.content, encoding="utf-8")
    print(res.status)
    return 0 if res.status in ("clean", "force-upstream") else 1


# ---- T8: Gate integrity verification (v1.8.0) -------------------------------
#
# Problem: `/vg:update` does a 3-way merge into AI-generated command files that
# mix prose + logic + structured data. A clean merge can still produce
# *logically broken* gate logic — a hard gate becomes soft via textual merge
# artifact undetectable by file-exists or SHA checks.
#
# Defense: upstream releases publish `gate-manifest.json` listing every
# enforced hard gate (heuristic: block contains `exit 1` OR `⛔ BLOCK`) with
# SHA256 of the block content. After merge, we re-locate each gate in the
# merged file, re-hash its block, and diff vs upstream hash. Mismatches are
# parked for interactive review via `/vg:reapply-patches --verify-gates`.

GATE_MANIFEST_URL_TMPL = (
    "https://github.com/vietdev99/vgflow/releases/download/v{version}/gate-manifest.json"
)


def fetch_gate_manifest(version: str, timeout: int = 10):
    """Download gate-manifest.json for the given upstream version.

    Returns parsed dict on success, None on 404 (pre-v1.8.0 release lacks it).
    Raises RuntimeError on other network/parse errors.
    """
    url = GATE_MANIFEST_URL_TMPL.format(version=version.lstrip("v"))
    req = urllib.request.Request(url, headers={"User-Agent": "vg-update/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # backward-compat: silently skip
        raise RuntimeError("gate-manifest fetch failed: HTTP {}".format(e.code))
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError("gate-manifest fetch failed: {}".format(e))


def _locate_gate_block(text: str, gate_id: str = "", fingerprint: str = ""):
    """Find a gate block in `text`, anchored on the unique step name.

    v2.41.3 (closes Issue #55 + #53 Bug #3) — primary anchor is the gate_id
    (= unique step name in the manifest), looked up via the canonical
    `<step name="{gate_id}">...</step>` boundary. Pre-v2.41.3 the locator
    used `text.find(fingerprint)` + `rfind("<step", ...)`: when the
    fingerprint substring also appeared inside an unrelated earlier `<step>`
    block (common boilerplate like "**Update PIPELINE-STATE.json:**"), it
    walked back to the wrong step tag and hashed the wrong block, producing
    a false-positive `content_hash_mismatch`.

    The fingerprint argument is retained as a fallback for legacy manifests
    and any non-`<step>` gate forms, but should be considered deprecated for
    step-wrapped gates.

    Returns (start_idx, end_idx) span or None.
    """
    if gate_id:
        # Match `<step name="{gate_id}">` allowing extra attrs (profile=, ...).
        # `re.DOTALL` + non-greedy body anchors to the FIRST `</step>` after
        # the open tag — the standard nested-step contract in review.md.
        pat = re.compile(
            r'<step\s+name="' + re.escape(gate_id) + r'"[^>]*>.*?</step>',
            re.DOTALL,
        )
        m = pat.search(text)
        if m:
            return (m.start(), m.end())
        # Step genuinely renamed / deleted — let caller report
        # gate_removed_by_merge instead of falling through to a wrong block.
        return None

    # Legacy fallback (deprecated): fingerprint-only lookup. Kept for
    # backwards compatibility with older `gate-manifest.json` payloads that
    # predate gate_id, and for any non-step gate forms (none currently).
    fp = fingerprint.strip()
    if not fp:
        return None
    idx = text.find(fp)
    if idx < 0:
        # Try a shorter prefix — merge may have edited the tail half of the fingerprint
        prefix = fp[: max(20, len(fp) // 2)]
        idx = text.find(prefix)
        if idx < 0:
            return None

    # Walk backward to nearest <step ...> (or BOF); forward to matching </step>
    step_open = text.rfind("<step", 0, idx)
    step_close = text.find("</step>", idx)
    if step_open >= 0 and step_close >= 0:
        return (step_open, step_close + len("</step>"))
    # Fallback: window of ±6000 chars
    return (max(0, idx - 3000), min(len(text), idx + 3000))


def verify_gate_integrity(
    merged_file_path: Path,
    manifest_gates: list,
    command_name: str,
):
    """Re-hash each gate block in `merged_file_path`; return list of conflicts.

    Each conflict dict: {gate_id, command, upstream_sha, local_sha,
                         upstream_block, merged_block}
    Gates belonging to other commands are skipped (caller drives per-file).
    """
    if not merged_file_path.exists():
        return []
    text = merged_file_path.read_text(encoding="utf-8")
    conflicts = []
    for g in manifest_gates:
        if g.get("command") != command_name:
            continue
        fp = g.get("fingerprint", "")
        gid = g.get("gate_id", "")
        expected = (g.get("block_pattern_sha256") or "").strip().lower()
        # v2.41.3 — gate_id (= unique step name) is the primary anchor;
        # fingerprint kept as fallback for legacy / non-step gates.
        span = _locate_gate_block(text, gid, fp)
        if not span:
            # Gate missing entirely — treat as hard conflict (merge removed it)
            conflicts.append({
                "gate_id": g.get("gate_id", "?"),
                "command": command_name,
                "upstream_sha": expected,
                "local_sha": "MISSING",
                "upstream_block": g.get("upstream_block", ""),
                "merged_block": "<gate block not found in merged file>",
                "reason": "gate_removed_by_merge",
            })
            continue
        start, end = span
        merged_block = text[start:end]
        local_sha = hashlib.sha256(
            merged_block.encode("utf-8", errors="replace")
        ).hexdigest()
        if local_sha != expected:
            conflicts.append({
                "gate_id": g.get("gate_id", "?"),
                "command": command_name,
                "upstream_sha": expected,
                "local_sha": local_sha,
                "upstream_block": g.get("upstream_block", ""),
                "merged_block": merged_block,
                "reason": "content_hash_mismatch",
            })
    return conflicts


def write_gate_conflicts_report(
    conflicts_by_file: dict,
    from_version: str,
    to_version: str,
    output_dir: Path,
):
    """Write gate-conflicts.md + per-gate unified diffs.

    Layout:
      {output_dir}/gate-conflicts.md
      {output_dir}/gate-conflicts/{command}-{gate_id}.diff

    Returns total conflict count.
    """
    import difflib

    report_path = output_dir / "gate-conflicts.md"
    diff_dir = output_dir / "gate-conflicts"
    diff_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    lines = [
        "# Gate Integrity Conflicts (v{} → v{})".format(from_version, to_version),
        "",
        "Glossary: merge (gộp) · gate (cổng enforcement) · conflict (xung đột) · verify (xác minh).",
        "",
        "`/vg:update` detected that the 3-way merge altered one or more HARD gate",
        "blocks in ways the syntactic SHA256 file-level check could not catch.",
        "A HARD gate might now be logically SOFT. Resolve before `/vg:build`.",
        "",
        "## Resolution",
        "",
        "Run `/vg:reapply-patches --verify-gates` for an interactive side-by-side",
        "walk-through: use upstream / keep merged / skip + flag manual / cancel.",
        "",
        "---",
        "",
    ]

    for rel_file, conflicts in conflicts_by_file.items():
        for c in conflicts:
            total += 1
            slug = "{}-{}".format(c["command"], c["gate_id"]).replace("/", "_")
            diff_file = diff_dir / "{}.diff".format(slug)
            up = c.get("upstream_block", "").splitlines(keepends=True)
            mg = c.get("merged_block", "").splitlines(keepends=True)
            diff_text = "".join(
                difflib.unified_diff(
                    up, mg,
                    fromfile="upstream/{}".format(rel_file),
                    tofile="merged/{}".format(rel_file),
                    n=3,
                )
            )
            diff_file.write_text(diff_text, encoding="utf-8")

            lines.extend([
                "## {} :: {}".format(c["command"], c["gate_id"]),
                "**Status:** CONFLICTED — merge (gộp) altered this hard gate (cổng)",
                "**File:** `{}`".format(rel_file),
                "**Reason:** `{}`".format(c.get("reason", "content_hash_mismatch")),
                "**Upstream SHA256:** `{}`".format(c["upstream_sha"]),
                "**Local SHA256:**    `{}`".format(c["local_sha"]),
                "**Side-by-side diff (xem song song):** `{}`".format(
                    diff_file.relative_to(output_dir).as_posix()
                ),
                "**Resolution (cách xử lý):** `/vg:reapply-patches --verify-gates`",
                "",
            ])

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return total


def _emit_gate_conflict_telemetry(conflict: dict, rel_file: str, phase: str = "") -> None:
    """Best-effort telemetry emit. Silent if telemetry disabled or jsonl unwriteable."""
    try:
        import uuid
        path = Path(".vg/telemetry.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "event_id": str(uuid.uuid4()),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "event_type": "gate_integrity_conflict",
            "phase": phase or None,
            "command": "vg:update",
            "step": "gate-integrity-verify",
            "gate_id": conflict.get("gate_id"),
            "outcome": "BLOCK",
            "payload": {
                "target_command": conflict.get("command"),
                "file": rel_file,
                "reason": conflict.get("reason"),
                "upstream_sha": conflict.get("upstream_sha"),
                "local_sha": conflict.get("local_sha"),
            },
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def cmd_verify_gates(args):
    """After /vg:update merge, verify hard gates survived intact.

    Inputs:
      --manifest-version  upstream version (e.g. "1.8.0")
      --from-version      local pre-update version (for report header)
      --merged-root       root dir of merged .claude install (default .claude)
      --output-dir        where to write gate-conflicts.md (default .vg/vgflow-patches)
      --manifest-file     optional local path to gate-manifest.json (skip download)
      --phase             optional phase tag for telemetry

    Returns 0 if no conflicts, 1 if conflicts found, 2 on backward-compat skip
    (manifest missing upstream — pre-v1.8.0 release).
    """
    output_dir = Path(args.output_dir)
    merged_root = Path(args.merged_root)

    manifest = None
    if args.manifest_file:
        mp = Path(args.manifest_file)
        if mp.exists():
            manifest = json.loads(mp.read_text(encoding="utf-8"))
    if manifest is None:
        try:
            manifest = fetch_gate_manifest(args.manifest_version)
        except RuntimeError as e:
            print("WARN (cảnh báo): {} — skipping gate verification (xác minh cổng).".format(e),
                  file=sys.stderr)
            return 0

    if manifest is None:
        print("WARN: upstream v{} has no gate-manifest.json — pre-v1.8.0, skipping verify.".format(
            args.manifest_version), file=sys.stderr)
        return 2

    gates = manifest.get("gates", [])
    if not gates:
        print("gate-manifest empty — nothing to verify.")
        return 0

    # Group by command → target file path
    cmd_to_file = {}
    for g in gates:
        cmd = g.get("command")
        if not cmd:
            continue
        cmd_to_file.setdefault(cmd, "commands/vg/{}.md".format(cmd))

    conflicts_by_file = {}
    for cmd, rel in cmd_to_file.items():
        merged = merged_root / rel
        cs = verify_gate_integrity(merged, gates, cmd)
        if cs:
            conflicts_by_file[rel] = cs
            for c in cs:
                _emit_gate_conflict_telemetry(c, rel, phase=args.phase or "")

    if not conflicts_by_file:
        print("✓ Gate integrity verified ({} gates across {} files).".format(
            len(gates), len(cmd_to_file)))
        return 0

    total = write_gate_conflicts_report(
        conflicts_by_file,
        from_version=args.from_version or "unknown",
        to_version=args.manifest_version,
        output_dir=output_dir,
    )
    print("⛔ {} gate integrity conflict(s) detected. See {}/gate-conflicts.md".format(
        total, output_dir.as_posix()))
    print("   Run `/vg:reapply-patches --verify-gates` to resolve.")
    return 1


# ---- T8: Release-side gate-manifest generator -------------------------------

def scan_hard_gates(commands_dir: Path):
    """Scan `commands_dir/*.md` for hard gate blocks.

    Heuristic: a block inside `<step ...> ... </step>` counts as a hard gate
    when it contains either `exit 1` OR the `⛔ BLOCK` marker.

    Returns list of gate dicts matching the manifest schema.
    """
    import re

    STEP_RE = re.compile(r'<step\s+name="([^"]+)"[^>]*>(.*?)</step>', re.DOTALL)
    gates = []

    for md in sorted(commands_dir.rglob("*.md")):
        # Skip _shared/ helpers — they're included by reference, not enforced
        rel = md.relative_to(commands_dir).as_posix()
        if rel.startswith("_shared/") or rel.startswith("_"):
            continue
        text = md.read_text(encoding="utf-8")
        command = md.stem  # filename without .md
        for m in STEP_RE.finditer(text):
            step_name = m.group(1)
            block = m.group(0)  # full <step>...</step>
            if ("exit 1" not in block) and ("⛔ BLOCK" not in block) and ("⛔  BLOCK" not in block):
                continue
            # Fingerprint = first 80 chars of the inner block content, stripped
            inner = m.group(2).strip()
            fingerprint = inner[:80]
            sha = hashlib.sha256(block.encode("utf-8")).hexdigest()
            # Approximate line range
            start_line = text.count("\n", 0, m.start()) + 1
            end_line = text.count("\n", 0, m.end()) + 1
            gates.append({
                "command": command,
                "gate_id": step_name,
                "block_pattern_sha256": sha,
                "block_lines_in_release": "{}-{}".format(start_line, end_line),
                "fingerprint": fingerprint,
                "upstream_block": block,  # included so reapply-patches can show diff
            })
    return gates


def cmd_build_gate_manifest(args):
    """Generate gate-manifest.json from a commands/vg/ directory.

    Usage (release CI):
      python vg_update.py build-gate-manifest \\
        --commands-dir commands/vg \\
        --version 1.8.0 \\
        --output gate-manifest.json
    """
    commands_dir = Path(args.commands_dir)
    if not commands_dir.is_dir():
        print("ERROR: commands dir not found: {}".format(commands_dir), file=sys.stderr)
        return 1
    gates = scan_hard_gates(commands_dir)
    manifest = {
        "version": args.version,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "heuristic": "block inside <step> containing `exit 1` OR `⛔ BLOCK`",
        "gates": gates,
    }
    out = Path(args.output)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Wrote {} ({} gates from {} command file(s)).".format(
        out, len(gates), len({g['command'] for g in gates})))
    return 0


def main():
    # v2.41.3 (Issue #53 Bug #2) — Windows console defaults to cp1252; any
    # print("⛔ ...") raises UnicodeEncodeError. Reconfigure stdout/stderr to
    # UTF-8 with replace-on-encode-fail so the helper still emits a parseable
    # message even on legacy consoles. No-op on Linux/macOS where the default
    # is already UTF-8.
    import sys
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc and enc not in ("utf-8", "utf8") and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass  # locked stream — caller already owns the encoding

    import argparse
    p = argparse.ArgumentParser(prog="vg-update")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="print current + latest + state")
    c.add_argument("--repo", default="vietdev99/vgflow")
    c.set_defaults(func=cmd_check)

    f = sub.add_parser("fetch", help="download tarball + verify + extract")
    f.add_argument("--repo", default="vietdev99/vgflow")
    f.set_defaults(func=cmd_fetch)

    m = sub.add_parser("merge", help="3-way merge a single file")
    m.add_argument("--ancestor", required=True)
    m.add_argument("--current", required=True)
    m.add_argument("--upstream", required=True)
    m.add_argument("--output", required=True)
    m.set_defaults(func=cmd_merge)

    # T8: post-merge gate integrity verification
    vg = sub.add_parser(
        "verify-gates",
        help="After 3-way merge, verify hard gates survived intact",
    )
    vg.add_argument("--manifest-version", required=True,
                    help="Upstream version (e.g. 1.8.0) used to download gate-manifest.json")
    vg.add_argument("--from-version", default="",
                    help="Local pre-update version (for report header)")
    vg.add_argument("--merged-root", default=".claude",
                    help="Root dir of merged install (default .claude)")
    vg.add_argument("--output-dir", default=".vg/vgflow-patches",
                    help="Where to write gate-conflicts.md")
    vg.add_argument("--manifest-file", default="",
                    help="Optional local path to gate-manifest.json (skip download)")
    vg.add_argument("--phase", default="",
                    help="Optional phase tag for telemetry event")
    vg.set_defaults(func=cmd_verify_gates)

    # T8: release-time gate-manifest generator
    bgm = sub.add_parser(
        "build-gate-manifest",
        help="Scan commands/vg/ for hard gates; emit gate-manifest.json (used by release CI)",
    )
    bgm.add_argument("--commands-dir", required=True,
                     help="Path to commands/vg/ (source of truth)")
    bgm.add_argument("--version", required=True,
                     help="Release version stamp (e.g. 1.8.0)")
    bgm.add_argument("--output", default="gate-manifest.json",
                     help="Output manifest path")
    bgm.set_defaults(func=cmd_build_gate_manifest)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
