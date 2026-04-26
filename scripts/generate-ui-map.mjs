#!/usr/bin/env node
/**
 * generate-ui-map.js — VG component hierarchy generator.
 *
 * CÔNG CỤ: Đọc code React/React Native/Vue/Svelte hiện có, vẽ ra cây component
 * dạng ASCII + JSON. Dùng cho 2 mục đích:
 *   1. As-is map (bản đồ hiện trạng): khi phase sửa view cũ → scan code để AI
 *      hiểu cấu trúc trước khi chỉnh.
 *   2. Verify drift (kiểm lệch hướng): sau khi build xong, scan lại code thực
 *      tế + so với UI-MAP.md (bản vẽ đích) do planner viết → phát hiện executor
 *      làm sai cấu trúc.
 *
 * PORT FROM: gist TongDucThanhNam (audited clean — chỉ đọc AST + xuất ASCII).
 *   - Bun → Node 20+ (dùng `parseArgs`, `fs/promises`)
 *   - Hardcoded `apps/mobile/src` + expo-router → config-driven qua CLI flags
 *   - Hỗ trợ thêm Vue / Svelte (best-effort — vẫn React/RN tốt nhất)
 *
 * USAGE:
 *   node generate-ui-map.js \
 *       --src apps/web/src \
 *       --entry apps/web/src/App.tsx \
 *       --alias @=apps/web/src \
 *       --format tree        # tree | json | both
 *       --output .vg/phases/10/UI-MAP-AS-IS.md
 *
 * PREREQUISITES:
 *   - Node 20+
 *   - @babel/parser + @babel/traverse (cài qua pnpm / npm)
 *
 * CONFIG-DRIVEN MODE:
 *   Nếu `.claude/vg.config.md` có section `ui_map`, có thể gọi không cần flag:
 *     ui_map:
 *       src: "apps/web/src"
 *       entry: "apps/web/src/App.tsx"
 *       aliases:
 *         - "@=apps/web/src"
 *       router: "react-router"   # react-router | next-app | expo-router | none
 *
 * NO EXTERNAL CALLS. Read-only on filesystem. Pure AST analysis.
 */

import path from "node:path"
import fs from "node:fs/promises"
import fsSync from "node:fs"
import { parseArgs } from "node:util"
import { createRequire } from "node:module"
import { fileURLToPath } from "node:url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(import.meta.url)

// Load @babel/parser + @babel/traverse — support multiple install locations
let parse, traverse
function loadBabel() {
  const candidates = [
    // Current project
    process.cwd(),
    // Sibling monorepo dir
    path.join(process.cwd(), "node_modules"),
    // Script's own dir (if published as VG tool)
    __dirname,
    path.join(__dirname, "node_modules"),
  ]
  let parserMod, traverseMod
  for (const root of candidates) {
    try {
      const req = createRequire(path.join(root, "_placeholder.js"))
      parserMod = parserMod || req("@babel/parser")
      traverseMod = traverseMod || req("@babel/traverse")
      if (parserMod && traverseMod) break
    } catch {
      // Try next
    }
  }
  if (!parserMod || !traverseMod) {
    console.error(
      "⛔ Thiếu @babel/parser hoặc @babel/traverse.\n" +
      "   Cài: pnpm add -D @babel/parser @babel/traverse\n" +
      "   Hoặc: npm install -D @babel/parser @babel/traverse"
    )
    process.exit(1)
  }
  parse = parserMod.parse
  traverse = traverseMod.default || traverseMod
}

// --- CLI CONFIGURATION ---
const HELP_TEXT = `Usage: node generate-ui-map.js [options]

CLI options (override config):
  --src <path>             Source directory (required nếu không có config)
  --entry <path>           Entry file (required nếu không có config)
  --root-component <name>  Root component name override (tuỳ chọn)
  --alias <key=value>      Path aliases, lặp lại nhiều lần (vd --alias @=src)
  --focus <name>           Focus on a specific component
  --scope <mode>           Focus scope: up|full|down (default: down)
                             up   = ancestors → target (children collapsed)
                             full = ancestors → target → full subtree
                             down = target as root → full subtree
  --layout-only            Chỉ giữ class layout (flex, grid, padding...)
  --format <fmt>           tree | json | both (default: tree)
  --output <path>          Ghi ra file thay vì stdout (markdown wrapper nếu .md)
  --router <name>          Router hint: expo-router|next-app|react-router|none
                             (auto-detect nếu bỏ trống)
  --config <path>          Path tới vg.config.md (default: .claude/vg.config.md)

PHASE 15 — wave-scoped extraction (D-12a/b/e + D-14):
  --owner-wave-id <id>     Filter output tree to subtree owned by wave-id.
                             Reads <uimap-source> planner UI-MAP if given to
                             cross-reference owner_wave_id tags + matches
                             scanned components by file path. Used by
                             /vg:build post-wave-commit drift gate (T7.3).
  --owner-task-id <id>     Further filter to a single task's subtree (D-14
                             Haiku context optimization). Requires
                             --owner-wave-id when used.
  --uimap-source <path>    Planner UI-MAP.md to cross-reference owner_*_id
                             tags (default: ./UI-MAP.md if present).
  --full-tree              Explicit "no filter" (alias for default behavior;
                             documents intent in build scripts).
  -h, --help               Show this help

EXAMPLES:
  # As-is map cho phase update UI hiện có
  node generate-ui-map.js --src apps/web/src --entry apps/web/src/App.tsx \\
      --output .vg/phases/11-user-settings/UI-MAP-AS-IS.md

  # Focus 1 component + cả tổ tiên + cả con
  node generate-ui-map.js --src src --entry src/app.tsx \\
      --focus DealWizard --scope full

  # Phase 15 — wave-scoped subtree for build post-wave drift gate
  node generate-ui-map.js --src apps/web/src --entry apps/web/src/App.tsx \\
      --owner-wave-id wave-1 \\
      --uimap-source .vg/phases/7.14.3/UI-MAP.md \\
      --format json --output .vg/phases/7.14.3/.wave-1-asbuilt.json
`

const EXTENSIONS = [".tsx", ".ts", ".jsx", ".js", ".vue", ".svelte"]

function parseCli(argv) {
  const { values } = parseArgs({
    args: argv.slice(2),
    options: {
      src: { type: "string" },
      entry: { type: "string" },
      "root-component": { type: "string" },
      alias: { type: "string", multiple: true, default: [] },
      focus: { type: "string" },
      scope: { type: "string", default: "down" },
      "layout-only": { type: "boolean", default: false },
      format: { type: "string", default: "tree" },
      output: { type: "string" },
      router: { type: "string" },
      config: { type: "string", default: ".claude/vg.config.md" },
      // Phase 15 D-12a/b/e + D-14 — wave-scoped subtree extraction
      "owner-wave-id": { type: "string" },
      "owner-task-id": { type: "string" },
      "uimap-source": { type: "string" },
      "full-tree": { type: "boolean", default: false },
      help: { type: "boolean", short: "h", default: false },
    },
    strict: true,
  })
  return values
}


// --- Phase 15 D-12a/b/e + D-14 — wave-scoped subtree filter ---
//
// Cross-reference planner UI-MAP.md (which has owner_wave_id / owner_task_id
// tags per node per D-15 schema) against the as-built tree (scanned from
// code) by COMPONENT NAME + FILE PATH. Filter as-built tree to nodes whose
// corresponding planner node is tagged with the target owner-wave-id (and
// optional owner-task-id).
//
// Convention:
//   - Planner UI-MAP.md JSON code block: nodes have `tag` (component name),
//     `owner_wave_id`, optional `owner_task_id`, `children`.
//   - As-built tree: nodes have `name` (component name), `file`, `children`.
//   - Matching: as-built.name == planner.tag.
//
// If a planner node has owner_wave_id matching target, that node + all
// descendants are kept. If owner_wave_id is absent, the node is kept only if
// any descendant matches (sparse tagging support).
function loadPlannerOwnership(uimapPath) {
  // Returns Map<componentName, {wave, task}> from planner UI-MAP.md JSON block.
  if (!uimapPath || !fsSync.existsSync(uimapPath)) return new Map()
  const text = fsSync.readFileSync(uimapPath, "utf8")
  const match = text.match(/```json\s*\n([\s\S]*?)\n```/)
  if (!match) return new Map()
  let data
  try { data = JSON.parse(match[1]) } catch (_) { return new Map() }

  const ownership = new Map()
  function walk(node, inheritedWave, inheritedTask) {
    if (!node || typeof node !== "object") return
    const wave = node.owner_wave_id || inheritedWave || null
    const task = node.owner_task_id || inheritedTask || null
    const name = node.tag || node.name
    if (name && (wave || task)) {
      // First-write wins (root tag captures top-level ownership)
      if (!ownership.has(name)) ownership.set(name, { wave, task })
    }
    const children = node.children || []
    for (const c of children) walk(c, wave, task)
  }
  const root = data.root || data
  walk(root, null, null)
  return ownership
}

function filterTreeByOwnership(node, ownership, targetWave, targetTask) {
  // Returns filtered copy of node, or null if neither node nor any descendant
  // matches the target ownership.
  if (!node || typeof node !== "object") return null
  const meta = ownership.get(node.name) || {}
  const waveMatch = meta.wave === targetWave
  const taskMatch = !targetTask || meta.task === targetTask
  const inScope = waveMatch && taskMatch

  const children = node.children || []
  const keptChildren = []
  for (const c of children) {
    const kc = filterTreeByOwnership(c, ownership, targetWave, targetTask)
    if (kc) keptChildren.push(kc)
  }
  if (!inScope && keptChildren.length === 0) return null
  return { ...node, children: keptChildren }
}

function applyPhase15Filter(tree, values) {
  const targetWave = values["owner-wave-id"]
  const targetTask = values["owner-task-id"]
  if (!targetWave) return tree  // no filter requested

  if (targetTask && !targetWave) {
    console.error("⛔ --owner-task-id requires --owner-wave-id")
    process.exit(1)
  }

  // Resolve uimap-source: explicit > ./UI-MAP.md
  let uimapPath = values["uimap-source"]
  if (!uimapPath && fsSync.existsSync("UI-MAP.md")) uimapPath = "UI-MAP.md"
  if (!uimapPath) {
    console.error(
      "⛔ --owner-wave-id requires --uimap-source <path> (or UI-MAP.md in cwd) " +
      "to cross-reference owner_wave_id tags. As-built scan has no ownership metadata."
    )
    process.exit(1)
  }
  const ownership = loadPlannerOwnership(uimapPath)
  if (ownership.size === 0) {
    console.error(`⚠ ${uimapPath} has no owner_wave_id/owner_task_id tags — filter passes through unchanged.`)
    return tree
  }
  const filtered = filterTreeByOwnership(tree, ownership, targetWave, targetTask || null)
  if (!filtered) {
    console.error(
      `⚠ owner-wave-id=${targetWave}` +
      (targetTask ? ` + owner-task-id=${targetTask}` : "") +
      ` matches 0 components in scanned tree. Empty subtree returned.`
    )
    return { name: "(empty)", children: [] }
  }
  return filtered
}

function loadConfigSection(configPath) {
  if (!fsSync.existsSync(configPath)) return null
  const txt = fsSync.readFileSync(configPath, "utf8")
  // Parse `ui_map:` section (YAML-like block)
  const match = txt.match(/^ui_map:\s*$([\s\S]*?)(?=^\S|\Z)/m)
  if (!match) return null
  const section = match[1]
  const cfg = {}
  for (const line of section.split(/\r?\n/)) {
    const m = line.match(/^\s{2,}([a-z_]+):\s*"?([^"#\n]+?)"?\s*(?:#.*)?$/i)
    if (m) cfg[m[1]] = m[2].trim()
  }
  // Parse aliases array (YAML list)
  const aliasMatch = section.match(/^\s{2,}aliases:\s*$([\s\S]*?)(?=^\s{0,2}[a-z_]+:|\Z)/m)
  if (aliasMatch) {
    cfg.aliases = []
    for (const line of aliasMatch[1].split(/\r?\n/)) {
      const am = line.match(/^\s*-\s*"?([^"#\n]+?)"?\s*(?:#.*)?$/)
      if (am) cfg.aliases.push(am[1].trim())
    }
  }
  return cfg
}

// --- LAYOUT & STYLE CONSTANTS (same as gist, framework-agnostic) ---
const LAYOUT_CLASS_EXACT = new Set([
  "absolute", "contents", "fixed", "flex", "grid", "grow", "hidden",
  "inline", "relative", "shrink", "static", "sticky",
])

const LAYOUT_CLASS_PREFIXES = [
  "-bottom-", "-inset-", "-left-", "-m-", "-mb-", "-ml-", "-mr-", "-mt-", "-mx-", "-my-",
  "-right-", "-top-", "absolute", "aspect-", "basis-", "bottom-", "col-", "content-",
  "display-", "end-", "flex-", "gap-", "grid-", "grow-", "h-", "inset-", "items-",
  "justify-", "left-", "m-", "max-h-", "max-w-", "mb-", "min-h-", "min-w-", "ml-",
  "mr-", "mt-", "mx-", "my-", "order-", "overflow-", "overscroll-", "p-", "pb-", "pe-",
  "pl-", "place-", "pr-", "ps-", "pt-", "px-", "py-", "right-", "row-", "self-",
  "shrink-", "size-", "space-x-", "space-y-", "start-", "top-", "w-", "z-",
]

const STYLE_KEYS = new Set([
  "alignContent", "alignItems", "alignSelf", "aspectRatio", "bottom", "display",
  "end", "flex", "flexBasis", "flexDirection", "flexGrow", "flexShrink", "flexWrap",
  "gap", "height", "inset", "insetBlockEnd", "insetBlockStart", "insetInlineEnd",
  "insetInlineStart", "justifyContent", "left", "margin", "marginBottom",
  "marginHorizontal", "marginLeft", "marginRight", "marginTop", "marginVertical",
  "maxHeight", "maxWidth", "minHeight", "minWidth", "overflow", "padding",
  "paddingBottom", "paddingHorizontal", "paddingLeft", "paddingRight", "paddingTop",
  "paddingVertical", "position", "right", "start", "top", "width", "zIndex",
])

// --- ROUTER DETECTION ---
const ROUTER_SIGNATURES = {
  "expo-router": {
    imports: ["expo-router"],
    routeComponents: ["Stack.Screen", "Tabs.Screen", "Drawer.Screen"],
    nameAttribute: "name",
  },
  "next-app": {
    imports: ["next/navigation", "next/link"],
    routeComponents: [],  // Next 13+ routing is file-based, no JSX routes
    nameAttribute: null,
  },
  "react-router": {
    imports: ["react-router", "react-router-dom"],
    routeComponents: ["Route"],
    nameAttribute: "path",
  },
  "tanstack-router": {
    imports: ["@tanstack/router", "@tanstack/react-router"],
    routeComponents: ["Route"],
    nameAttribute: "path",
  },
  none: {
    imports: [],
    routeComponents: [],
    nameAttribute: null,
  },
}

function detectRouter(allImports) {
  for (const [name, sig] of Object.entries(ROUTER_SIGNATURES)) {
    if (sig.imports.some((mod) => allImports.has(mod))) return name
  }
  return "none"
}

// --- UTILS ---
function parseAst(source, filename) {
  return parse(source, {
    sourceType: "module",
    sourceFilename: filename,
    errorRecovery: true,
    plugins: [
      "jsx", "typescript", "classProperties", "decorators-legacy",
      "dynamicImport", "topLevelAwait", "importAttributes",
    ],
  })
}

function rel(filePath, rootDir) {
  return path.relative(rootDir, filePath).split(path.sep).join("/")
}

function isComponentName(name) {
  return /^[A-Z][A-Za-z0-9]*$/.test(name || "")
}

function inferComponentName(filePath) {
  const ext = path.extname(filePath)
  let base = path.basename(filePath, ext)
  if (base.toLowerCase() === "index") base = path.basename(path.dirname(filePath))
  return base
    .split(/[^a-zA-Z0-9]+/g)
    .filter(Boolean)
    .map((p) => `${p[0]?.toUpperCase() ?? ""}${p.slice(1)}`)
    .join("")
}

function unwrapExpression(node) {
  let current = node
  while (
    current &&
    ["ParenthesizedExpression", "TSAsExpression", "TSTypeAssertion", "TSNonNullExpression"].includes(
      current.type,
    )
  ) {
    current = current.expression
  }
  return current
}

function jsxNameToString(nameNode) {
  if (!nameNode) return null
  if (nameNode.type === "JSXIdentifier") return nameNode.name
  if (nameNode.type === "JSXMemberExpression") {
    const left = jsxNameToString(nameNode.object)
    const right = jsxNameToString(nameNode.property)
    return left && right ? `${left}.${right}` : null
  }
  return null
}

function sourceSlice(source, node) {
  if (!node || typeof node.start !== "number" || typeof node.end !== "number") return null
  return source.slice(node.start, node.end).replace(/\s+/g, " ").trim()
}

function pushClassTokens(out, value) {
  if (!value) return
  for (const token of value.split(/\s+/).map((i) => i.trim()).filter(Boolean)) out.push(token)
}

function normalizeClassTokens(tokens) {
  const seen = new Set()
  return tokens.filter((t) => t && !seen.has(t) && seen.add(t)).join(" ")
}

function isLayoutClass(token) {
  const base = token.replace(/^(?:[a-zA-Z0-9_-]+:)+/, "")
  return LAYOUT_CLASS_EXACT.has(base) || LAYOUT_CLASS_PREFIXES.some((p) => base.startsWith(p))
}

function filterLayoutClasses(className) {
  if (!className) return null
  const filtered = className
    .split(/\s+/)
    .map((i) => i.trim())
    .filter(Boolean)
    .filter(isLayoutClass)
  return filtered.length > 0 ? filtered.join(" ") : null
}

// --- AST EXTRACTION (logic copied from gist, simplified) ---
function collectImports(ast) {
  const imports = new Map()
  traverse(ast, {
    ImportDeclaration(p) {
      const source = p.node.source.value
      for (const spec of p.node.specifiers || []) {
        if (spec.type === "ImportDefaultSpecifier") {
          imports.set(spec.local.name, { source, kind: "default", importedName: "default" })
        } else if (spec.type === "ImportNamespaceSpecifier") {
          imports.set(spec.local.name, { source, kind: "namespace", importedName: "*" })
        } else if (spec.type === "ImportSpecifier") {
          imports.set(spec.local.name, {
            source, kind: "named",
            importedName: spec.imported.type === "Identifier" ? spec.imported.name : spec.imported.value,
          })
        }
      }
    },
  })
  return imports
}

function collectBindings(ast) {
  const bindings = new Map()
  traverse(ast, {
    VariableDeclarator(p) {
      if (p.node.id?.type === "Identifier" && p.node.init && !bindings.has(p.node.id.name)) {
        bindings.set(p.node.id.name, p.node.init)
      }
    },
  })
  return bindings
}

function hasChildrenParam(fn) {
  return (fn?.params || []).some(
    (p) =>
      p.type === "ObjectPattern" &&
      p.properties?.some(
        (prop) =>
          prop.type === "ObjectProperty" && prop.key?.type === "Identifier" && prop.key.name === "children",
      ),
  )
}

function findJsxInExpression(node) {
  const c = unwrapExpression(node)
  if (!c) return null
  if (c.type === "JSXElement" || c.type === "JSXFragment") return c
  if (c.type === "CallExpression") {
    for (const a of c.arguments || []) {
      const f = findJsxInExpression(a)
      if (f) return f
    }
    return findJsxInExpression(c.callee)
  }
  if (c.type === "ArrayExpression") {
    for (const el of c.elements || []) {
      const f = findJsxInExpression(el)
      if (f) return f
    }
    return null
  }
  if (["ConditionalExpression", "LogicalExpression", "BinaryExpression"].includes(c.type)) {
    return (
      findJsxInExpression(c.left) ||
      findJsxInExpression(c.right) ||
      findJsxInExpression(c.consequent) ||
      findJsxInExpression(c.alternate)
    )
  }
  if (c.type === "ArrowFunctionExpression" || c.type === "FunctionExpression") {
    return extractReturnJsx(c)
  }
  return null
}

function findReturnJsxInStatement(s) {
  if (!s) return null
  if (s.type === "ReturnStatement") return s.argument ? findJsxInExpression(s.argument) : null
  if (s.type === "BlockStatement") {
    for (const ch of s.body || []) {
      const f = findReturnJsxInStatement(ch)
      if (f) return f
    }
    return null
  }
  if (s.type === "IfStatement")
    return findReturnJsxInStatement(s.consequent) || findReturnJsxInStatement(s.alternate)
  return null
}

function extractReturnJsx(fn) {
  if (
    fn.type === "ArrowFunctionExpression" &&
    (fn.body.type === "JSXElement" || fn.body.type === "JSXFragment")
  ) {
    return fn.body
  }
  if (fn.body?.type !== "BlockStatement") return findJsxInExpression(fn.body)
  for (const s of fn.body.body || []) {
    const f = findReturnJsxInStatement(s)
    if (f) return f
  }
  return null
}

function createExpressionFlow(node) {
  const c = unwrapExpression(node)
  return c ? { kind: "expression", node: c } : null
}

function buildRenderFlowFromStatements(statements, source, fallback = null) {
  let cur = fallback
  for (let i = statements.length - 1; i >= 0; i--) {
    const next = buildRenderFlowFromStatement(statements[i], source, cur)
    if (next) cur = next
  }
  return cur
}

function buildRenderFlowFromStatement(s, source, fallback = null) {
  if (!s) return fallback
  if (s.type === "ReturnStatement") return s.argument ? createExpressionFlow(s.argument) : null
  if (s.type === "BlockStatement") return buildRenderFlowFromStatements(s.body || [], source, fallback)
  if (s.type === "IfStatement") {
    const thenF = buildRenderFlowFromStatement(s.consequent, source, fallback) || fallback
    const elseF = s.alternate
      ? buildRenderFlowFromStatement(s.alternate, source, fallback) || fallback
      : fallback
    if (!thenF && !elseF) return fallback
    return { kind: "branch", condition: s.test, thenFlow: thenF, elseFlow: elseF }
  }
  return fallback
}

function extractRenderFlow(fn, source) {
  if (fn.type === "ArrowFunctionExpression" && (fn.body.type === "JSXElement" || fn.body.type === "JSXFragment")) {
    return createExpressionFlow(fn.body)
  }
  if (fn.body?.type !== "BlockStatement") return createExpressionFlow(fn.body)
  return buildRenderFlowFromStatements(fn.body.body || [], source)
}

function unwrapComponentFunction(node) {
  let c = unwrapExpression(node)
  while (c) {
    if (["ArrowFunctionExpression", "FunctionExpression", "FunctionDeclaration"].includes(c.type)) return c
    if (c.type === "CallExpression") {
      const fnArg = (c.arguments || []).find((a) =>
        ["ArrowFunctionExpression", "FunctionExpression"].includes(unwrapExpression(a)?.type),
      )
      if (fnArg) return unwrapExpression(fnArg)
      c = unwrapExpression((c.arguments || [])[0])
      continue
    }
    break
  }
  return null
}

// --- STYLING & LAYOUT RESOLUTION (simplified from gist) ---
function collectClassTokensFromExpression(node, bindings, source, seen = new Set(), out = []) {
  const c = unwrapExpression(node)
  if (!c) return out
  if (c.type === "StringLiteral") { pushClassTokens(out, c.value); return out }
  if (c.type === "TemplateLiteral") {
    for (const q of c.quasis || []) pushClassTokens(out, q.value?.cooked ?? q.value?.raw ?? "")
    for (const e of c.expressions || []) collectClassTokensFromExpression(e, bindings, source, seen, out)
    return out
  }
  if (c.type === "Identifier") {
    if (!bindings.has(c.name) || seen.has(c.name)) return out
    seen.add(c.name)
    collectClassTokensFromExpression(bindings.get(c.name), bindings, source, seen, out)
    seen.delete(c.name)
    return out
  }
  if (c.type === "ArrayExpression") {
    for (const el of c.elements || []) collectClassTokensFromExpression(el, bindings, source, seen, out)
    return out
  }
  if (["ConditionalExpression", "LogicalExpression"].includes(c.type)) {
    collectClassTokensFromExpression(c.consequent, bindings, source, seen, out)
    collectClassTokensFromExpression(c.alternate, bindings, source, seen, out)
    collectClassTokensFromExpression(c.left, bindings, source, seen, out)
    collectClassTokensFromExpression(c.right, bindings, source, seen, out)
  }
  return out
}

function summarizeStyleExpression(node, bindings, source, seen = new Set(), entries = new Map()) {
  const c = unwrapExpression(node)
  if (!c) return entries
  if (c.type === "Identifier") {
    if (!bindings.has(c.name) || seen.has(c.name)) return entries
    seen.add(c.name)
    summarizeStyleExpression(bindings.get(c.name), bindings, source, seen, entries)
    seen.delete(c.name)
    return entries
  }
  if (c.type === "ObjectExpression") {
    for (const p of c.properties || []) {
      if (p?.type !== "ObjectProperty") continue
      let k = null
      if (!p.computed && p.key.type === "Identifier") k = p.key.name
      else if (!p.computed && p.key.type === "StringLiteral") k = p.key.value
      if (!k || !STYLE_KEYS.has(k)) continue
      entries.set(k, p.value.type === "StringLiteral" ? p.value.value : sourceSlice(source, p.value) ?? "?")
    }
  }
  return entries
}

function summarizeElementLayout(jsxNode, bindings, source, layoutOnly) {
  if (!jsxNode || jsxNode.type !== "JSXElement") return null
  const seg = []
  for (const attr of jsxNode.openingElement.attributes || []) {
    if (attr.type !== "JSXAttribute" || attr.name.type !== "JSXIdentifier") continue
    const p = attr.name.name
    if (p === "className" || p.endsWith("ClassName")) {
      const toks = []
      if (attr.value?.type === "StringLiteral") pushClassTokens(toks, attr.value.value)
      else if (attr.value?.type === "JSXExpressionContainer" && attr.value.expression) {
        collectClassTokensFromExpression(attr.value.expression, bindings, source, new Set(), toks)
      }
      const norm = normalizeClassTokens(toks)
      const final = layoutOnly ? filterLayoutClasses(norm) : norm
      if (final) seg.push(p === "className" ? final : `${p}=${final}`)
    } else if (p.endsWith("Style") && attr.value?.type === "JSXExpressionContainer" && attr.value.expression) {
      const entries = summarizeStyleExpression(attr.value.expression, bindings, source)
      if (entries.size > 0)
        seg.push(`${p}={${[...entries.entries()].map(([k, v]) => `${k}:${v}`).join(", ")}}`)
    }
  }
  return seg.length > 0 ? seg.join(" | ") : null
}

function getStringJsxAttribute(jsxNode, attrName) {
  if (!jsxNode || jsxNode.type !== "JSXElement") return null
  for (const attr of jsxNode.openingElement.attributes || []) {
    if (attr.type === "JSXAttribute" && attr.name.type === "JSXIdentifier" && attr.name.name === attrName) {
      if (attr.value?.type === "StringLiteral") return attr.value.value
      if (attr.value?.type === "JSXExpressionContainer" && attr.value.expression?.type === "StringLiteral")
        return attr.value.expression.value
    }
  }
  return null
}

// --- FILE WALKING (replaces Bun.Glob) ---
async function walkSourceFiles(rootDir) {
  const out = []
  async function walk(dir) {
    let entries
    try {
      entries = await fs.readdir(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const e of entries) {
      const full = path.join(dir, e.name)
      if (e.isDirectory()) {
        if (e.name === "node_modules" || e.name.startsWith(".") || e.name === "__tests__") continue
        await walk(full)
      } else if (e.isFile()) {
        const ext = path.extname(e.name).toLowerCase()
        if (!EXTENSIONS.includes(ext)) continue
        if (e.name.includes(".test.") || e.name.includes(".spec.") || e.name.endsWith(".d.ts")) continue
        out.push(full)
      }
    }
  }
  await walk(rootDir)
  return out.sort((a, b) => a.localeCompare(b))
}

// --- MAIN ---
let nextNodeId = 1
function createNode(kind, name, overrides = {}) {
  return { id: `n${nextNodeId++}`, kind, name, children: [], ...overrides }
}

function cloneTreeNode(n) {
  return { ...n, id: `n${nextNodeId++}`, children: n.children.map(cloneTreeNode) }
}

function buildTextNode(raw) {
  const t = raw.replace(/\s+/g, " ").trim()
  return t ? createNode("text", "text", { text: t.length > 80 ? `${t.slice(0, 77)}...` : t }) : null
}

async function main() {
  const values = parseCli(process.argv)
  if (values.help) {
    console.log(HELP_TEXT)
    return
  }

  // Merge config + CLI
  const cfg = loadConfigSection(values.config) || {}
  const src = values.src || cfg.src
  const entry = values.entry || cfg.entry
  const aliasesRaw = values.alias.length > 0 ? values.alias : (cfg.aliases || [])
  const routerHint = values.router || cfg.router

  if (!src || !entry) {
    console.error(
      "⛔ Thiếu --src hoặc --entry (hoặc khai báo ui_map.src / ui_map.entry trong vg.config.md)",
    )
    process.exit(1)
  }

  const validScopes = new Set(["up", "full", "down"])
  if (!validScopes.has(values.scope)) {
    console.error(`⛔ --scope phải là một trong: ${[...validScopes].join(", ")}`)
    process.exit(1)
  }

  loadBabel()

  const PROJECT_ROOT = process.cwd()
  const srcDir = path.resolve(PROJECT_ROOT, src)
  const entryFile = path.resolve(PROJECT_ROOT, entry)

  const aliasMap = Object.fromEntries(
    aliasesRaw.map((pair) => {
      const idx = pair.indexOf("=")
      return idx < 0 ? [pair, ""] : [pair.slice(0, idx), pair.slice(idx + 1)]
    }),
  )

  // Read + parse all source files
  const files = await walkSourceFiles(srcDir)
  if (files.length === 0) {
    console.error(`⛔ Không tìm thấy file nào trong ${srcDir}`)
    process.exit(1)
  }

  async function analyzeFile(filePath) {
    const source = await fs.readFile(filePath, "utf8")
    let ast
    try {
      ast = parseAst(source, filePath)
    } catch (err) {
      console.error(`[warn] bỏ qua file không phân tích được ${rel(filePath, PROJECT_ROOT)}: ${err?.message || err}`)
      return null
    }

    const imports = collectImports(ast)
    const bindings = collectBindings(ast)
    const fileRel = rel(filePath, PROJECT_ROOT)
    const components = new Map()
    let defaultName = null

    function registerComponent(name, fn, isDefault = false) {
      if (!name || !isComponentName(name)) return
      const rootRender = extractRenderFlow(fn, source)
      const key = `${name}@${fileRel}`
      const rootLayout =
        rootRender?.kind === "expression" && rootRender.node?.type === "JSXElement"
          ? summarizeElementLayout(rootRender.node, bindings, source, false)
          : null
      components.set(name, {
        key, name, fileAbs: filePath, fileRel, rootRender, imports, bindings,
        source, acceptsChildren: hasChildrenParam(fn), isDefault, rootLayout,
      })
      if (isDefault) defaultName = name
    }

    traverse(ast, {
      FunctionDeclaration(p) {
        if (p.node.id?.name) registerComponent(p.node.id.name, p.node)
      },
      VariableDeclarator(p) {
        if (p.node.id?.type !== "Identifier" || !p.node.init) return
        const fn = unwrapComponentFunction(p.node.init)
        if (fn) registerComponent(p.node.id.name, fn)
      },
      ExportDefaultDeclaration(p) {
        const d = unwrapExpression(p.node.declaration)
        if (!d) return
        if (d.type === "Identifier") defaultName = d.name
        else if (["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"].includes(d.type)) {
          registerComponent(d.id?.name || inferComponentName(filePath) || "RootComponent", d, true)
        }
      },
    })

    return { fileAbs: filePath, fileRel, components, imports, defaultName }
  }

  const analyses = (await Promise.all(files.map(analyzeFile))).filter(Boolean)

  const componentsByKey = new Map()
  const componentsByFile = new Map()
  const defaultByFile = new Map()
  const expandedComponents = new Set()
  const allImports = new Set()

  for (const a of analyses) {
    componentsByFile.set(a.fileAbs, a.components)
    defaultByFile.set(a.fileAbs, a.defaultName)
    for (const c of a.components.values()) componentsByKey.set(c.key, c)
    for (const imp of a.imports.values()) allImports.add(imp.source)
  }

  const detectedRouter = routerHint || detectRouter(allImports)
  const routerSig = ROUTER_SIGNATURES[detectedRouter] || ROUTER_SIGNATURES.none

  function resolveAliasImport(source) {
    for (const [prefix, target] of Object.entries(aliasMap)) {
      if (!prefix || !target) continue
      if (source === prefix) return path.resolve(PROJECT_ROOT, target)
      if (source.startsWith(`${prefix}/`))
        return path.resolve(PROJECT_ROOT, target, source.slice(prefix.length + 1))
    }
    return null
  }

  function isProjectImportSource(source) {
    if (!source) return false
    if (source.startsWith(".")) return true
    return Object.keys(aliasMap).some((p) => source === p || source.startsWith(`${p}/`))
  }

  async function resolveImportToFile(fromFile, source) {
    const base = source.startsWith(".")
      ? path.resolve(path.dirname(fromFile), source)
      : resolveAliasImport(source)
    if (!base) return null
    try {
      await fs.access(base)
      return base
    } catch {}
    for (const ext of EXTENSIONS) {
      try {
        await fs.access(`${base}${ext}`)
        return `${base}${ext}`
      } catch {}
    }
    for (const ext of EXTENSIONS) {
      try {
        await fs.access(path.join(base, `index${ext}`))
        return path.join(base, `index${ext}`)
      } catch {}
    }
    return null
  }

  async function resolveLocalComponentKey(tagName, from) {
    if (!tagName.includes(".")) {
      const same = componentsByFile.get(from.fileAbs)?.get(tagName)
      if (same) return same.key
    }
    const local = tagName.split(".")[0] || tagName
    const imp = from.imports.get(local)
    if (!imp || !isProjectImportSource(imp.source)) return null
    const targetFile = await resolveImportToFile(from.fileAbs, imp.source)
    if (!targetFile) return null
    const tc = componentsByFile.get(targetFile)
    if (!tc) return null
    if (tagName.includes(".") && imp.kind === "namespace") {
      const last = tagName.split(".").pop() || ""
      if (tc.has(last)) return tc.get(last)?.key || null
      return tc.size === 1 ? [...tc.values()][0]?.key || null : null
    }
    if (imp.kind === "default") {
      const dn = defaultByFile.get(targetFile)
      if (dn && tc.has(dn)) return tc.get(dn)?.key || null
      return tc.size === 1 ? [...tc.values()][0]?.key || null : null
    }
    if (imp.kind === "named") return tc.get(imp.importedName)?.key || null
    return null
  }

  async function buildNodesFromRenderFlow(flow, ctx, stack, slotChildren) {
    if (!flow) return []
    if (flow.kind === "expression") return buildNodesFromExpression(flow.node, ctx, stack, slotChildren)
    const branch = createNode("branch", sourceSlice(ctx.source, flow.condition) || "condition")
    const th = await buildNodesFromRenderFlow(flow.thenFlow, ctx, stack, slotChildren)
    const el = await buildNodesFromRenderFlow(flow.elseFlow, ctx, stack, slotChildren)
    if (th.length > 0) branch.children.push(createNode("branch", "then", { children: th }))
    if (el.length > 0) branch.children.push(createNode("branch", "else", { children: el }))
    return branch.children.length > 0 ? [branch] : []
  }

  async function buildNodesFromExpression(expr, ctx, stack, slotChildren) {
    const c = unwrapExpression(expr)
    if (!c) return []
    if (c.type === "Identifier" && c.name === "children") return slotChildren.map(cloneTreeNode)
    if (c.type === "JSXElement" || c.type === "JSXFragment")
      return buildNodesFromJsx(c, ctx, stack, slotChildren)
    if (c.type === "ConditionalExpression") {
      const branch = createNode("branch", sourceSlice(ctx.source, c.test) || "condition")
      const th = await buildNodesFromExpression(c.consequent, ctx, stack, slotChildren)
      const el = await buildNodesFromExpression(c.alternate, ctx, stack, slotChildren)
      if (th.length > 0) branch.children.push(createNode("branch", "then", { children: th }))
      if (el.length > 0) branch.children.push(createNode("branch", "else", { children: el }))
      return branch.children.length > 0 ? [branch] : []
    }
    if (c.type === "LogicalExpression") {
      const ch = await buildNodesFromExpression(c.right, ctx, stack, slotChildren)
      return ch.length === 0
        ? []
        : [createNode("branch", sourceSlice(ctx.source, c.left) || "condition", { children: ch })]
    }
    if (c.type === "ArrayExpression") {
      const out = []
      for (const el of c.elements || []) out.push(...(await buildNodesFromExpression(el, ctx, stack, slotChildren)))
      return out
    }
    if (c.type === "CallExpression") {
      const out = []
      for (const a of c.arguments || []) out.push(...(await buildNodesFromExpression(a, ctx, stack, slotChildren)))
      return out
    }
    return []
  }

  async function buildChildrenFromJsxChildren(children, ctx, stack, slotChildren) {
    const out = []
    for (const ch of children || []) {
      if (!ch) continue
      if (ch.type === "JSXText") {
        const tn = buildTextNode(ch.value)
        if (tn) out.push(tn)
        continue
      }
      if (ch.type === "JSXExpressionContainer") {
        out.push(...(await buildNodesFromExpression(ch.expression, ctx, stack, slotChildren)))
        continue
      }
      out.push(...(await buildNodesFromJsx(ch, ctx, stack, slotChildren)))
    }
    return out
  }

  async function buildNodesFromJsx(jsxNode, ctx, stack, slotChildren) {
    if (!jsxNode) return []
    if (jsxNode.type === "JSXFragment")
      return buildChildrenFromJsxChildren(jsxNode.children || [], ctx, stack, slotChildren)
    if (jsxNode.type !== "JSXElement") return []

    const tagName = jsxNameToString(jsxNode.openingElement?.name)
    if (!tagName || tagName === "Fragment")
      return buildChildrenFromJsxChildren(jsxNode.children || [], ctx, stack, slotChildren)

    const directChildren = await buildChildrenFromJsxChildren(jsxNode.children || [], ctx, stack, slotChildren)
    const localKey = await resolveLocalComponentKey(tagName, ctx)

    if (localKey) {
      const target = componentsByKey.get(localKey)
      if (!target) return []
      const node = createNode("component", target.name, {
        fileRel: target.fileRel,
        layout: target.rootLayout,
      })
      if (stack.includes(localKey)) {
        node.recursive = true
        return [node]
      }
      if (expandedComponents.has(localKey)) {
        node.duplicate = true
        return [node]
      }
      expandedComponents.add(localKey)
      node.children = await buildNodesFromRenderFlow(target.rootRender, target, [...stack, localKey], directChildren)
      return [node]
    }

    const moduleName = ctx.imports.get(tagName.split(".")[0] || tagName)?.source
    const isModule = moduleName && !isProjectImportSource(moduleName)
    const layout = summarizeElementLayout(jsxNode, ctx.bindings, ctx.source, values["layout-only"])

    const fwNode = createNode("framework", tagName, {
      module: isModule ? moduleName : null,
      layout,
      children: directChildren,
    })

    // Router-aware: resolve route target if recognized
    if (isModule && routerSig.routeComponents.includes(tagName) && routerSig.nameAttribute) {
      const routeName = getStringJsxAttribute(jsxNode, routerSig.nameAttribute)
      if (routeName) {
        fwNode.children.unshift(createNode("text", "route", { text: `${routerSig.nameAttribute}=${routeName}` }))
      }
    }
    return [fwNode]
  }

  // Find root component
  let root = values["root-component"]
    ? [...componentsByKey.values()].find((c) => c.name === values["root-component"])
    : null
  if (!root && defaultByFile.get(entryFile))
    root = componentsByFile.get(entryFile)?.get(defaultByFile.get(entryFile))
  if (!root) root = [...componentsByKey.values()].find((c) => c.fileAbs === entryFile) || null
  if (!root) {
    console.error(
      `⛔ Không xác định được component gốc từ ${rel(entryFile, PROJECT_ROOT)}.\n` +
      `   Gợi ý: --root-component <TênComponent>`,
    )
    process.exit(1)
  }

  const rootNode = createNode("component", root.name, { fileRel: root.fileRel, layout: root.rootLayout })
  rootNode.children = await buildNodesFromRenderFlow(root.rootRender, root, [root.key], [])

  // --- ASCII OUTPUT ---
  function fmtLabel(n) {
    if (n.kind === "text" || n.kind === "branch") {
      if (n.kind === "text") return `"${n.text || ""}"`
      return `⊘ ${n.name}`
    }
    const parts = [`[${n.name}]`]
    if (n.fileRel) parts.push(`- ${n.fileRel}`)
    else if (n.module) parts.push(`- ${n.module}`)
    if (n.layout) parts.push(`(${n.layout})`)
    if (n.recursive) parts.push("↺")
    if (n.duplicate) parts.push("(xem phía trên)")
    return parts.join(" ")
  }

  function buildAsciiTree(rn) {
    const lines = []
    function walk(n, prefix, isLast, depth) {
      const conn = depth === 0 ? "" : isLast ? "└── " : "├── "
      lines.push(`${prefix}${conn}${fmtLabel(n)}`)
      for (let i = 0; i < n.children.length; i++) {
        walk(
          n.children[i],
          depth === 0 ? "" : `${prefix}${isLast ? "    " : "│   "}`,
          i === n.children.length - 1,
          depth + 1,
        )
      }
    }
    walk(rn, "", true, 0)
    return lines.join("\n")
  }

  const ascii = buildAsciiTree(rootNode)

  // Build JSON tree (stable shape for diff)
  function toJson(n) {
    const o = { kind: n.kind, name: n.name }
    if (n.fileRel) o.file = n.fileRel
    if (n.module) o.module = n.module
    if (n.layout) o.layout = n.layout
    if (n.recursive) o.recursive = true
    if (n.duplicate) o.duplicate = true
    if (n.text) o.text = n.text
    if (n.children.length > 0) o.children = n.children.map(toJson)
    return o
  }
  let json = toJson(rootNode)

  // Phase 15 D-12a/b/e + D-14 — wave-scoped subtree filter (operates on JSON output)
  const format = values.format || "tree"
  if (values["owner-wave-id"]) {
    json = applyPhase15Filter(json, values)
    if (format !== "json") {
      console.error(
        "⚠ --owner-wave-id filter applied to JSON output only. ASCII tree " +
        "remains full (use --format json for filtered output)."
      )
    }
  } else if (values["full-tree"]) {
    // Explicit no-filter (intent documentation; same as default)
  }

  // Output
  let outContent = ""
  if (format === "tree") {
    outContent = ascii
  } else if (format === "json") {
    outContent = JSON.stringify(json, null, 2)
  } else if (format === "both") {
    outContent = `## ASCII Tree\n\n\`\`\`\n${ascii}\n\`\`\`\n\n## JSON\n\n\`\`\`json\n${JSON.stringify(json, null, 2)}\n\`\`\`\n`
  }

  if (values.output) {
    let wrapped = outContent
    if (values.output.endsWith(".md")) {
      const now = new Date().toISOString().slice(0, 10)
      wrapped = `# UI Component Map\n\n` +
        `**Generated:** ${now}\n` +
        `**Root:** ${root.name} (${root.fileRel})\n` +
        `**Router detected:** ${detectedRouter}\n` +
        `**Source:** ${src}\n\n` +
        `---\n\n` +
        (format === "both" ? outContent : `## Component tree\n\n\`\`\`\n${ascii}\n\`\`\`\n`)
    }
    await fs.writeFile(values.output, wrapped, "utf8")
    console.error(`✓ UI map written to ${values.output}`)
  } else {
    console.log(outContent)
  }
}

main().catch((err) => {
  console.error(`generate-ui-map failed: ${err?.message || err}`)
  process.exit(1)
})
