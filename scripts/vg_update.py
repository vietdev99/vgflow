"""VG workflow update helper.

Handles version compare, SHA256 verify, 3-way merge, patches manifest,
GitHub releases query, and CLI subcommands (check / fetch / merge).
"""
from __future__ import annotations

import hashlib
import json
import os
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
        # Conservative: no ancestor means can't safely merge.
        # Only clean if current == upstream.
        cur_text = current.read_text(encoding="utf-8")
        up_text = upstream.read_text(encoding="utf-8")
        if cur_text == up_text:
            return MergeResult("clean", cur_text)
        return MergeResult("conflict", cur_text)

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
        )
        # Exit code: 0 = clean, N>0 = N conflicts, <0 = error
        status = "clean" if r.returncode == 0 else "conflict"
        return MergeResult(status, r.stdout)
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
    """3-way merge a single file and write merged content to --output."""
    res = three_way_merge(Path(args.ancestor), Path(args.current), Path(args.upstream))
    Path(args.output).write_text(res.content, encoding="utf-8")
    print(res.status)
    return 0 if res.status == "clean" else 1


def main():
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

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
