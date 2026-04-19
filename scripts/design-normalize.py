#!/usr/bin/env python3
"""
Universal design asset normalizer for VG workflow.

Converts design assets (HTML/PNG/JPG/PenBoard/Figma/Pencil/Stitch) into:
  - Screenshots (PNG) — ground truth for AI vision
  - Optional structural references (cleaned HTML / JSON page tree / XML / interactions)

Usage:
    python design-normalize.py <input> --output <dir> [--states] [--slug <name>]
    python design-normalize.py --batch '<glob>' --output <dir>
    python design-normalize.py --list-handlers

Output structure:
    <output>/screenshots/<slug>.<state>.png
    <output>/refs/<slug>.structural.<ext>
    <output>/refs/<slug>.interactions.md
    <output>/manifest.json
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

FORMAT_HANDLERS = {
    '.html': 'playwright_render',
    '.htm': 'playwright_render',
    '.png': 'passthrough',
    '.jpg': 'passthrough',
    '.jpeg': 'passthrough',
    '.webp': 'passthrough',
    '.fig': 'figma_fallback',
    '.pb': 'penboard_render',
    '.xml': 'pencil_xml',
}


def detect_format(path: Path) -> str:
    """Return handler name for the given asset path."""
    ext = path.suffix.lower()
    if ext in FORMAT_HANDLERS:
        # Special case: .xml could be Pencil or unrelated
        if ext == '.xml':
            # Pencil XMLs typically have <Document> with Pencil namespace
            try:
                head = path.read_text(encoding='utf-8', errors='ignore')[:500]
                if 'pencil' in head.lower() or 'xmlns:p=' in head:
                    return 'pencil_xml'
                return 'unknown'
            except OSError:
                return 'unknown'
        return FORMAT_HANDLERS[ext]
    return 'unknown'


# ---------------------------------------------------------------------------
# Handlers (skeleton — implementations in separate tasks)
# ---------------------------------------------------------------------------

def handler_passthrough(input_path: Path, output_dir: Path, slug: str, **kwargs) -> dict:
    """PNG/JPG/WEBP: copy (or convert JPG→PNG) to screenshots/."""
    screenshots_dir = output_dir / 'screenshots'
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    out = screenshots_dir / f'{slug}.default.png'

    ext = input_path.suffix.lower()
    if ext in ('.jpg', '.jpeg', '.webp'):
        try:
            from PIL import Image
            Image.open(input_path).convert('RGB').save(out, 'PNG')
        except ImportError:
            # Fallback: copy as-is, preserve extension
            fallback = screenshots_dir / f'{slug}.default{ext}'
            shutil.copy(input_path, fallback)
            out = fallback
    else:
        shutil.copy(input_path, out)

    return {
        'slug': slug,
        'handler': 'passthrough',
        'screenshots': [str(out.relative_to(output_dir))],
        'structural': None,
        'interactions': None,
    }


def handler_playwright_render(input_path: Path, output_dir: Path, slug: str,
                              capture_states: bool = False, **kwargs) -> dict:
    """HTML prototype → Playwright render → screenshot + cleaned HTML + interactions.

    Delegates to design-normalize-html.js (Node script using playwright).
    """
    import subprocess
    helper = Path(__file__).parent / 'design-normalize-html.js'
    if not helper.exists():
        raise FileNotFoundError(f'Missing helper: {helper}')

    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = ['node', str(helper), str(input_path.resolve()), str(output_dir.resolve()), slug]
    if capture_states:
        cmd.append('--states')

    # Timeout (plus overhead) for Playwright launch + render
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return {
            'slug': slug, 'handler': 'playwright_render',
            'error': 'Playwright render timeout (>90s)',
            'screenshots': [], 'structural': None, 'interactions': None,
        }

    if result.returncode != 0:
        # Helper emits JSON error to stderr OR stdout
        err_payload = result.stderr or result.stdout
        try:
            parsed = json.loads(err_payload.strip().split('\n')[-1])
            return {
                'slug': slug, 'handler': 'playwright_render',
                'error': parsed.get('error', err_payload),
                'screenshots': [], 'structural': None, 'interactions': None,
            }
        except (json.JSONDecodeError, IndexError):
            return {
                'slug': slug, 'handler': 'playwright_render',
                'error': f'Helper exit {result.returncode}: {err_payload[:300]}',
                'screenshots': [], 'structural': None, 'interactions': None,
            }

    # Parse final line of stdout as JSON result
    try:
        payload = json.loads(result.stdout.strip().split('\n')[-1])
    except (json.JSONDecodeError, IndexError):
        return {
            'slug': slug, 'handler': 'playwright_render',
            'error': f'Helper returned non-JSON: {result.stdout[:300]}',
            'screenshots': [], 'structural': None, 'interactions': None,
        }
    return payload


def handler_penboard_render(input_path: Path, output_dir: Path, slug: str, **kwargs) -> dict:
    """PenBoard .pb (JSON) → parse pages + extract structural tree.

    MVP strategy:
    - Parse JSON (.pb is plain JSON)
    - Extract pages + node tree → save as structural JSON
    - For PNG: look for sibling {stem}.png or {stem}-{page_slug}.png next to .pb
    - If no PNG sibling: emit warning; user exports from PenBoard app manually

    Full headless Electron render is out-of-scope for MVP (complex, slow).
    """
    screenshots_dir = output_dir / 'screenshots'
    refs_dir = output_dir / 'refs'
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    refs_dir.mkdir(parents=True, exist_ok=True)

    try:
        doc = json.loads(input_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        return {
            'slug': slug, 'handler': 'penboard_render',
            'error': f'Invalid PenBoard JSON: {e}',
            'screenshots': [], 'structural': None, 'interactions': None,
        }

    pages = doc.get('pages', [])
    if not pages:
        # Single-page fallback: doc.children
        children = doc.get('children', [])
        pages = [{'id': 'root', 'name': slug, 'children': children}]

    # Extract simplified structural per page
    page_structs = []
    for page in pages:
        page_struct = {
            'id': page.get('id'),
            'name': page.get('name'),
            'nodes': _penboard_flatten_nodes(page.get('children', [])),
        }
        page_structs.append(page_struct)

    structural = {
        'source': 'penboard',
        'version': doc.get('version'),
        'pages': page_structs,
        'connections': doc.get('connections', []),
        'data_entities': doc.get('dataEntities', []),
    }
    structural_path = refs_dir / f'{slug}.structural.json'
    structural_path.write_text(json.dumps(structural, indent=2), encoding='utf-8')

    # Look for sibling PNGs (user-exported from PenBoard)
    screenshots = []
    parent = input_path.parent
    stem = input_path.stem
    # Patterns: {stem}.png, {stem}-login.png, {stem}_page1.png
    for candidate in list(parent.glob(f'{stem}*.png')) + list(parent.glob(f'{stem}*.jpg')):
        target = screenshots_dir / f'{slug}.{candidate.stem.replace(stem, "default").lstrip("-_")}.png'
        try:
            shutil.copy(candidate, target)
            screenshots.append(str(target.relative_to(output_dir)))
        except OSError:
            pass

    result = {
        'slug': slug, 'handler': 'penboard_render',
        'screenshots': screenshots,
        'structural': str(structural_path.relative_to(output_dir)),
        'interactions': None,
        'pages': [{'id': p['id'], 'name': p['name']} for p in page_structs],
    }
    if not screenshots:
        result['warning'] = (
            f'No PNG screenshot found for PenBoard asset. '
            f'Export from PenBoard app → save as "{stem}.png" next to .pb file. '
            f'Structural JSON saved: {structural_path.name}'
        )
    return result


def _penboard_flatten_nodes(children: list, depth: int = 0, max_depth: int = 4) -> list:
    """Flatten PenBoard node tree to AI-friendly list (limit depth to avoid bloat)."""
    nodes = []
    for c in children:
        if not isinstance(c, dict):
            continue
        node = {
            'id': c.get('id'),
            'type': c.get('type'),
            'name': c.get('name'),
            'bounds': {
                'x': c.get('x'), 'y': c.get('y'),
                'w': c.get('width'), 'h': c.get('height'),
            },
        }
        # Keep a few display hints
        for key in ('text', 'fill', 'fontSize', 'layout', 'justifyContent', 'alignItems', 'padding'):
            if key in c:
                node[key] = c[key]
        # Recurse (bounded)
        if depth < max_depth and c.get('children'):
            node['children'] = _penboard_flatten_nodes(c['children'], depth + 1, max_depth)
        elif c.get('children'):
            node['children_count'] = len(c['children'])
        nodes.append(node)
    return nodes


def handler_pencil_xml(input_path: Path, output_dir: Path, slug: str, **kwargs) -> dict:
    """Pencil XML → copy XML as structural, look for sibling PNG.

    Pencil's native rendering requires Pencil GUI. MVP: preserve XML for AI,
    use sibling PNG if user exported.
    """
    refs_dir = output_dir / 'refs'
    screenshots_dir = output_dir / 'screenshots'
    refs_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    # Copy XML as structural reference
    structural_path = refs_dir / f'{slug}.structural.xml'
    shutil.copy(input_path, structural_path)

    # Look for sibling PNG (same stem)
    screenshots = []
    for candidate in input_path.parent.glob(f'{input_path.stem}*.png'):
        target = screenshots_dir / f'{slug}.default.png'
        shutil.copy(candidate, target)
        screenshots.append(str(target.relative_to(output_dir)))
        break

    result = {
        'slug': slug, 'handler': 'pencil_xml',
        'screenshots': screenshots,
        'structural': str(structural_path.relative_to(output_dir)),
        'interactions': None,
    }
    if not screenshots:
        result['warning'] = (
            'No PNG screenshot found. Open Pencil → File → Export → PNG → save next to .xml '
            f'as "{input_path.stem}.png". Re-run to include screenshot.'
        )
    return result


def handler_figma_fallback(input_path: Path, output_dir: Path, slug: str, **kwargs) -> dict:
    """Figma .fig → user must export manually (no MCP detection at this layer).

    If user has Figma MCP configured, they should use it directly from Claude.
    This handler only preserves the path + looks for sibling PNG.
    """
    refs_dir = output_dir / 'refs'
    screenshots_dir = output_dir / 'screenshots'
    refs_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    # Look for sibling PNG
    screenshots = []
    for candidate in input_path.parent.glob(f'{input_path.stem}*.png'):
        target = screenshots_dir / f'{slug}.default.png'
        shutil.copy(candidate, target)
        screenshots.append(str(target.relative_to(output_dir)))

    # Record hint file
    hint_path = refs_dir / f'{slug}.figma-source.txt'
    hint_path.write_text(
        f'Figma source: {input_path}\n\n'
        f'To provide visual reference for AI:\n'
        f'  1. Open Figma → select frame → Export → PNG (2x) → save next to .fig as "{input_path.stem}.png"\n'
        f'  2. OR use Figma MCP server from Claude directly (if configured)\n',
        encoding='utf-8',
    )

    result = {
        'slug': slug, 'handler': 'figma_fallback',
        'screenshots': screenshots,
        'structural': str(hint_path.relative_to(output_dir)),
        'interactions': None,
    }
    if not screenshots:
        result['warning'] = f'Figma file detected but no sibling PNG. See {hint_path.name} for export steps.'
    return result


def handler_unknown(input_path: Path, output_dir: Path, slug: str, **kwargs) -> dict:
    """Unknown format → log + skip."""
    return {
        'slug': slug,
        'handler': 'unknown',
        'error': f'Unknown format for {input_path.name}. Supported: {list(FORMAT_HANDLERS.keys())}',
        'screenshots': [],
        'structural': None,
        'interactions': None,
    }


HANDLER_MAP = {
    'passthrough': handler_passthrough,
    'playwright_render': handler_playwright_render,
    'penboard_render': handler_penboard_render,
    'pencil_xml': handler_pencil_xml,
    'figma_fallback': handler_figma_fallback,
    'unknown': handler_unknown,
}


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

def make_slug(path: Path, base_dir: Optional[Path] = None) -> str:
    """Generate filesystem-safe slug from asset path."""
    if base_dir:
        try:
            rel = path.relative_to(base_dir)
        except ValueError:
            rel = path
    else:
        rel = Path(path.name)
    # Replace separators and drop extension
    stem = rel.with_suffix('')
    slug = str(stem).replace('\\', '/').replace('/', '-').replace(' ', '_')
    # Keep alnum + hyphen + underscore
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in slug).strip('_').lower()


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def normalize_one(input_path: Path, output_dir: Path, slug: Optional[str] = None,
                  capture_states: bool = False, base_dir: Optional[Path] = None) -> dict:
    """Normalize a single asset → dict manifest entry."""
    if not input_path.exists():
        return {'error': f'Not found: {input_path}', 'handler': 'error'}

    if slug is None:
        slug = make_slug(input_path, base_dir)

    fmt = detect_format(input_path)
    handler = HANDLER_MAP.get(fmt, handler_unknown)

    try:
        result = handler(input_path, output_dir, slug, capture_states=capture_states)
        result['source'] = str(input_path)
        result['format'] = fmt
        return result
    except NotImplementedError as e:
        return {
            'slug': slug, 'source': str(input_path), 'format': fmt,
            'handler': fmt, 'error': f'Not implemented yet: {e}',
            'screenshots': [], 'structural': None, 'interactions': None,
        }
    except Exception as e:
        return {
            'slug': slug, 'source': str(input_path), 'format': fmt,
            'handler': fmt, 'error': f'{type(e).__name__}: {e}',
            'screenshots': [], 'structural': None, 'interactions': None,
        }


def normalize_batch(inputs: list[Path], output_dir: Path, capture_states: bool = False,
                    base_dir: Optional[Path] = None) -> list[dict]:
    """Normalize multiple assets → list of manifest entries."""
    return [normalize_one(p, output_dir, capture_states=capture_states, base_dir=base_dir)
            for p in inputs]


def write_manifest(output_dir: Path, entries: list[dict]) -> Path:
    """Write manifest.json summarizing all normalized assets."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / 'manifest.json'
    manifest = {
        'version': '1',
        'total': len(entries),
        'succeeded': sum(1 for e in entries if not e.get('error')),
        'failed': sum(1 for e in entries if e.get('error')),
        'assets': entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description='Normalize design assets for VG workflow.',
    )
    parser.add_argument('input', nargs='?', help='Single asset path (or --batch glob)')
    parser.add_argument('--batch', help='Glob pattern for multiple assets')
    parser.add_argument('--output', '-o', required=False,
                        help='Output directory (default: .vg/design-normalized/)')
    parser.add_argument('--slug', help='Override auto-generated slug (single input only)')
    parser.add_argument('--states', action='store_true',
                        help='Capture interactive states (click triggers) for HTML assets')
    parser.add_argument('--base-dir', help='Base directory for slug generation (preserves relative path)')
    parser.add_argument('--list-handlers', action='store_true', help='List supported formats and exit')

    args = parser.parse_args(argv)

    if args.list_handlers:
        print('Supported formats:')
        for ext, h in sorted(FORMAT_HANDLERS.items()):
            print(f'  {ext:10} → {h}')
        return 0

    if not args.input and not args.batch:
        parser.error('Must provide <input> or --batch <glob>')

    output_dir = Path(args.output) if args.output else Path('.vg/design-normalized')
    base_dir = Path(args.base_dir) if args.base_dir else None

    # Collect inputs
    if args.batch:
        inputs = sorted(Path('.').glob(args.batch))
        if not inputs:
            print(f'No files matched pattern: {args.batch}', file=sys.stderr)
            return 1
    else:
        inputs = [Path(args.input)]

    # Normalize
    if len(inputs) == 1 and args.slug:
        entries = [normalize_one(inputs[0], output_dir, slug=args.slug,
                                 capture_states=args.states, base_dir=base_dir)]
    else:
        entries = normalize_batch(inputs, output_dir, capture_states=args.states,
                                  base_dir=base_dir)

    # Write manifest
    manifest_path = write_manifest(output_dir, entries)

    # Summary
    ok = sum(1 for e in entries if not e.get('error'))
    fail = len(entries) - ok
    print(f'Processed {len(entries)} asset(s): {ok} OK, {fail} failed')
    print(f'Manifest: {manifest_path}')
    for e in entries:
        status = 'ERROR' if e.get('error') else 'OK'
        source = e.get('source', '?')
        handler = e.get('handler', '?')
        print(f'  [{status:5}] {handler:20} {source}')
        if e.get('error'):
            print(f'          → {e["error"]}')

    return 0 if fail == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
