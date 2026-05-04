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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

FORMAT_HANDLERS = {
    '.html': 'playwright_render',
    '.htm': 'playwright_render',
    '.png': 'passthrough',         # may upgrade to passthrough_ocr if .structural.png (D-01)
    '.jpg': 'passthrough',
    '.jpeg': 'passthrough',
    '.webp': 'passthrough',
    '.fig': 'figma_fallback',
    '.pb': 'penboard_render',      # legacy JSON file parser
    '.xml': 'pencil_xml',          # legacy XML parser
    # Phase 15 D-01 — MCP-based handlers (Pencil + Penboard, 2 separate MCP servers)
    '.pen': 'pencil_mcp',          # encrypted Pencil file via mcp__pencil__*
    '.penboard': 'penboard_mcp',   # PenBoard workspace via mcp__penboard__*
    '.flow': 'penboard_mcp',       # PenBoard flow file via mcp__penboard__*
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
    """PNG/JPG/WEBP: copy (or convert JPG→PNG) to screenshots/.

    Phase 15 D-01: when input is *.structural.png OR sibling marker file
    {input_path.stem}.structural.marker exists, ALSO run OCR + region detection
    pipeline → emit refs/<slug>.structural.json (box-list per
    structural-json.v1.json). Default passthrough preserved for photo
    screenshots.
    """
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

    result = {
        'slug': slug,
        'handler': 'passthrough',
        'screenshots': [str(out.relative_to(output_dir))],
        'structural': None,
        'interactions': None,
    }

    # Phase 15 D-01: opt-in OCR + region detection for *.structural.png marker.
    # User decision #3: chỉ apply khi marker; default passthrough giữ cho photo.
    is_structural = (
        input_path.name.lower().endswith('.structural.png') or
        (input_path.parent / f'{input_path.stem}.structural.marker').exists()
    )
    if ext == '.png' and is_structural:
        refs_dir = output_dir / 'refs'
        refs_dir.mkdir(parents=True, exist_ok=True)
        ocr_result = _ocr_structural_png(input_path)
        if ocr_result is None:
            result['warning'] = (
                'PNG marked .structural.png but opencv-python + pytesseract not '
                'installed. Run: pip install opencv-python pytesseract  (also '
                'requires Tesseract binary in PATH). Falling back to passthrough only.'
            )
        else:
            structural_path = refs_dir / f'{slug}.structural.json'
            structural_path.write_text(
                json.dumps(ocr_result, indent=2), encoding='utf-8',
            )
            result['structural'] = str(structural_path.relative_to(output_dir))
            result['handler'] = 'passthrough_ocr'  # signal upgraded variant

    return result


def _ocr_structural_png(input_path: Path) -> Optional[dict]:
    """OCR + region detection for structural PNG mockup (Phase 15 D-01).

    Returns box-list per structural-json.v1.json schema, or None if cv2 +
    pytesseract unavailable (caller falls back to passthrough + warning).

    Pipeline:
      1. opencv: grayscale → Canny edges → morph close → contour detection
      2. Filter contours: drop tiny (<20px) and page-spanning (>90%)
      3. Per region: pytesseract OCR with --psm 6 (single uniform block)
      4. Emit unified node tree (page root + region children)
    """
    try:
        import cv2  # opencv-python
        import pytesseract
    except ImportError:
        return None

    img = cv2.imread(str(input_path))
    if img is None:
        return None

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Region detection: edge → close → contour
    edges = cv2.Canny(gray, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw < 20 or ch < 20:                      # tiny noise
            continue
        if cw * ch > w * h * 0.9:                   # page-spanning frame
            continue
        region_img = gray[y:y + ch, x:x + cw]
        try:
            text = pytesseract.image_to_string(region_img, config='--psm 6').strip()
        except Exception:
            text = ''
        regions.append({
            'tag': 'region',
            'id': f'r{len(regions)}',
            'classes': [],
            'role': None,
            'text': text if text else None,
            'bbox': {'x': int(x), 'y': int(y), 'w': int(cw), 'h': int(ch)},
            'children': [],
        })

    return {
        'format_version': '1.0',
        'source_format': 'png-structural',
        'extracted_at': datetime.now(timezone.utc).isoformat(),
        'source_path': str(input_path),
        'root': {
            'tag': 'page',
            'classes': [],
            'role': None,
            'text': None,
            'bbox': {'x': 0, 'y': 0, 'w': int(w), 'h': int(h)},
            'children': regions,
        },
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
        # v2.45.1 (Issue #72) — without explicit encoding, Python on Windows
        # defaults to locale.getpreferredencoding() (cp1258 on VN, cp1252 on
        # other Western locales). UTF-8 bytes ≥ 0x80 emitted by Playwright
        # stdout (em-dash, smart quotes, etc.) crash the reader thread with
        # UnicodeDecodeError → result.stdout becomes None → manifest aggregator
        # marks all assets as 'failed' with AttributeError 'NoneType' has no
        # attribute strip — even when PNG screenshots + structural refs DID
        # render successfully on disk. Same class of bug fixed in vg_update.py
        # for v2.41.3 (Issue #53 Bug #1).
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=90,
            encoding="utf-8", errors="replace",
        )
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


def handler_pencil_mcp(input_path: Path, output_dir: Path, slug: str, **kwargs) -> dict:
    """Pencil .pen → MCP-extracted structural via mcp__pencil__* (Phase 15 D-01).

    .pen files are ENCRYPTED — only readable through Pencil MCP server tools.
    Python subprocess cannot call MCP tools directly (those are AI-context tools).

    DELEGATION CONVENTION:
    The AI orchestrator (Haiku scanner in /vg:design-extract Layer 2) MUST call
    these MCP tools BEFORE invoking this normalizer:
      - mcp__pencil__open_document(input_path)
      - mcp__pencil__get_editor_state
      - mcp__pencil__batch_get        → node tree
      - mcp__pencil__export_nodes     → element box-list
      - mcp__pencil__get_screenshot   → default screenshot
    Save raw outputs to:
      {output_dir}/.tmp/{slug}.pencil-raw.json     # combined node tree + boxes
      {output_dir}/.tmp/{slug}.pencil-screenshot.png

    This handler then converts raw → structural-json.v1.json + copies screenshot.
    See commands/vg/design-extract.md Layer 2 MCP delegation pattern.
    """
    refs_dir = output_dir / 'refs'
    screenshots_dir = output_dir / 'screenshots'
    tmp_dir = output_dir / '.tmp'
    refs_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    raw_path = tmp_dir / f'{slug}.pencil-raw.json'
    screenshot_src = tmp_dir / f'{slug}.pencil-screenshot.png'

    if not raw_path.exists():
        return {
            'slug': slug, 'handler': 'pencil_mcp',
            'screenshots': [], 'structural': None, 'interactions': None,
            'mcp_handler_used': True,
            'error': (
                f'Pencil MCP raw output not found at {raw_path}. AI orchestrator '
                f'must call mcp__pencil__* tools first and save outputs to .tmp/. '
                f'See commands/vg/design-extract.md Layer 2 MCP delegation pattern.'
            ),
        }

    try:
        raw = json.loads(raw_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        return {
            'slug': slug, 'handler': 'pencil_mcp',
            'screenshots': [], 'structural': None, 'interactions': None,
            'mcp_handler_used': True,
            'error': f'Invalid Pencil MCP raw JSON ({raw_path}): {e}',
        }

    structural = _convert_pencil_mcp_to_structural(raw, input_path)
    structural_path = refs_dir / f'{slug}.structural.json'
    structural_path.write_text(json.dumps(structural, indent=2), encoding='utf-8')

    screenshots = []
    if screenshot_src.exists():
        screenshot_dst = screenshots_dir / f'{slug}.default.png'
        shutil.copy(screenshot_src, screenshot_dst)
        screenshots.append(str(screenshot_dst.relative_to(output_dir)))

    return {
        'slug': slug, 'handler': 'pencil_mcp',
        'screenshots': screenshots,
        'structural': str(structural_path.relative_to(output_dir)),
        'interactions': None,
        'mcp_handler_used': True,
    }


def _convert_pencil_mcp_to_structural(raw: dict, source_path: Path) -> dict:
    """Convert mcp__pencil__batch_get / get_editor_state output → structural-json.v1.json.

    Pencil node format (from MCP):
      {"id": "...", "type": "rect|text|group|...", "x": N, "y": N,
       "width": N, "height": N, "fill": "...", "fontSize": N,
       "text": "...", "children": [...]}
    """
    def convert_node(n: dict) -> dict:
        node = {
            'tag': n.get('type', 'unknown'),
            'id': n.get('id'),
            'classes': [],          # Pencil doesn't use CSS classes
            'role': None,
            'text': n.get('text'),
            'children': [convert_node(c) for c in n.get('children', []) if isinstance(c, dict)],
        }
        if any(k in n for k in ('x', 'y', 'width', 'height')):
            node['bbox'] = {
                'x': n.get('x', 0),
                'y': n.get('y', 0),
                'w': n.get('width', 0),
                'h': n.get('height', 0),
            }
        style_keys = ('fill', 'stroke', 'fontSize', 'fontFamily', 'opacity', 'strokeWidth')
        style = {k: n[k] for k in style_keys if k in n}
        if style:
            node['style'] = style
        return node

    # Raw can be: full document {"root": ...} or {"document": ...} or just the node
    root_raw = raw.get('root') or raw.get('document') or raw
    return {
        'format_version': '1.0',
        'source_format': 'pencil-mcp',
        'extracted_at': datetime.now(timezone.utc).isoformat(),
        'source_path': str(source_path),
        'root': convert_node(root_raw),
    }


def handler_penboard_mcp(input_path: Path, output_dir: Path, slug: str, **kwargs) -> dict:
    """Penboard .penboard / .flow → MCP-extracted structural via mcp__penboard__* (Phase 15 D-01).

    DELEGATION CONVENTION (parallel to handler_pencil_mcp):
    AI orchestrator (Haiku in /vg:design-extract Layer 2) MUST call:
      - mcp__penboard__list_flows
      - mcp__penboard__read_flow(flow_name)        per flow
      - mcp__penboard__read_doc(doc_id)            for doc nodes
      - mcp__penboard__manage_entities             entity bindings
      - mcp__penboard__manage_connections          data flow
      - mcp__penboard__generate_preview            screenshot
    Save raw outputs to:
      {output_dir}/.tmp/{slug}.penboard-raw.json   # combined flows + docs + entities + connections
      {output_dir}/.tmp/{slug}.penboard-preview.png

    This handler converts raw → structural-json.v1.json + copies preview screenshot.
    """
    refs_dir = output_dir / 'refs'
    screenshots_dir = output_dir / 'screenshots'
    tmp_dir = output_dir / '.tmp'
    refs_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    raw_path = tmp_dir / f'{slug}.penboard-raw.json'
    preview_src = tmp_dir / f'{slug}.penboard-preview.png'

    if not raw_path.exists():
        return {
            'slug': slug, 'handler': 'penboard_mcp',
            'screenshots': [], 'structural': None, 'interactions': None,
            'mcp_handler_used': True,
            'error': (
                f'Penboard MCP raw output not found at {raw_path}. AI orchestrator '
                f'must call mcp__penboard__* tools first and save outputs to .tmp/. '
                f'See commands/vg/design-extract.md Layer 2 MCP delegation pattern.'
            ),
        }

    try:
        raw = json.loads(raw_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        return {
            'slug': slug, 'handler': 'penboard_mcp',
            'screenshots': [], 'structural': None, 'interactions': None,
            'mcp_handler_used': True,
            'error': f'Invalid Penboard MCP raw JSON ({raw_path}): {e}',
        }

    structural = _convert_penboard_mcp_to_structural(raw, input_path)
    structural_path = refs_dir / f'{slug}.structural.json'
    structural_path.write_text(json.dumps(structural, indent=2), encoding='utf-8')

    # Interactions map from connections (data flow edges)
    interactions_path = None
    connections = raw.get('connections', [])
    if connections:
        lines = [f'# Interactions — {slug} (Penboard MCP)\n', f'\nExtracted from: {input_path}\n']
        lines.append(f'\n## Data flow connections ({len(connections)})\n\n')
        for conn in connections[:100]:
            src = conn.get('source') or conn.get('from') or '?'
            dst = conn.get('target') or conn.get('to') or '?'
            label = conn.get('label') or conn.get('type') or ''
            lines.append(f'- `{src}` → `{dst}`{(" — " + label) if label else ""}\n')
        interactions_path = refs_dir / f'{slug}.interactions.md'
        interactions_path.write_text(''.join(lines), encoding='utf-8')

    screenshots = []
    if preview_src.exists():
        preview_dst = screenshots_dir / f'{slug}.default.png'
        shutil.copy(preview_src, preview_dst)
        screenshots.append(str(preview_dst.relative_to(output_dir)))

    return {
        'slug': slug, 'handler': 'penboard_mcp',
        'screenshots': screenshots,
        'structural': str(structural_path.relative_to(output_dir)),
        'interactions': str(interactions_path.relative_to(output_dir)) if interactions_path else None,
        'mcp_handler_used': True,
    }


def _convert_penboard_mcp_to_structural(raw: dict, source_path: Path) -> dict:
    """Convert mcp__penboard__read_flow + read_doc + manage_entities → structural-json.v1.json.

    Penboard raw shape (combined by orchestrator):
      {
        "flows": [{"id": ..., "name": ..., "pages": [{"nodes": [...]}]}, ...],
        "docs":  [{"id": ..., "content": ...}, ...],
        "entities": [{"id": ..., "type": ..., "fields": [...]}, ...],
        "connections": [{"source": ..., "target": ..., ...}, ...]
      }
    """
    def convert_pb_node(n: dict) -> dict:
        node = {
            'tag': n.get('type') or n.get('kind') or 'unknown',
            'id': n.get('id'),
            'classes': [],
            'role': None,
            'text': n.get('text') or n.get('label'),
            'children': [convert_pb_node(c) for c in n.get('children', n.get('nodes', [])) if isinstance(c, dict)],
        }
        if any(k in n for k in ('x', 'y', 'width', 'height')):
            node['bbox'] = {'x': n.get('x', 0), 'y': n.get('y', 0),
                            'w': n.get('width', 0), 'h': n.get('height', 0)}
        if 'props' in n or 'data' in n:
            node['props'] = n.get('props') or n.get('data') or {}
        return node

    flows = raw.get('flows', [])
    flow_children = []
    for flow in flows:
        flow_node = {
            'tag': 'flow',
            'id': flow.get('id'),
            'classes': [],
            'role': None,
            'text': flow.get('name'),
            'children': [],
        }
        for page in flow.get('pages', []):
            page_node = {
                'tag': 'page',
                'id': page.get('id'),
                'classes': [],
                'role': None,
                'text': page.get('name'),
                'children': [convert_pb_node(n) for n in page.get('nodes', []) if isinstance(n, dict)],
            }
            flow_node['children'].append(page_node)
        flow_children.append(flow_node)

    return {
        'format_version': '1.0',
        'source_format': 'penboard-mcp',
        'extracted_at': datetime.now(timezone.utc).isoformat(),
        'source_path': str(source_path),
        'root': {
            'tag': 'workspace',
            'id': raw.get('workspace_id'),
            'classes': [],
            'role': None,
            'text': raw.get('workspace_name'),
            'props': {
                'entities_count': len(raw.get('entities', [])),
                'connections_count': len(raw.get('connections', [])),
            },
            'children': flow_children,
        },
    }


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
    'penboard_render': handler_penboard_render,    # legacy .pb file parser
    'penboard_mcp': handler_penboard_mcp,          # Phase 15 D-01 — .penboard/.flow via mcp__penboard__*
    'pencil_xml': handler_pencil_xml,              # legacy .xml parser
    'pencil_mcp': handler_pencil_mcp,              # Phase 15 D-01 — .pen via mcp__pencil__*
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
