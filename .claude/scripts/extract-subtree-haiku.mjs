#!/usr/bin/env node
/**
 * extract-subtree-haiku.mjs — Phase 15 D-14 subtree extraction.
 *
 * PURE JSON filter on planner UI-MAP.md. Extracts ~50-line subtree owned by
 * a specific wave (and optionally task) for injection into Sonnet executor
 * prompts via /vg:build step 8c (per Phase 15 D-12a + D-14).
 *
 * The "Haiku" in the filename is aspirational: D-14 originally proposed
 * spawning a Haiku sub-agent to extract subtree (cost optimization vs giving
 * Sonnet executor the full UI-MAP). In practice, deterministic JSON filter
 * via this script is faster + free + reproducible. Build step 8c invokes
 * this script directly via Bash; no Haiku invocation needed.
 *
 * USAGE:
 *   node extract-subtree-haiku.mjs \
 *       --uimap .vg/phases/7.14.3/UI-MAP.md \
 *       --owner-wave-id wave-1 \
 *       [--owner-task-id T-3] \
 *       [--format markdown|json|raw] \
 *       [--output <path>]
 *
 *   --uimap          REQUIRED — path to planner UI-MAP.md (with ```json``` block)
 *   --owner-wave-id  REQUIRED — wave identifier to filter by
 *   --owner-task-id  OPTIONAL — further filter to single task (D-14 single-task scope)
 *   --format         OPTIONAL — markdown (default; for AI prompt injection),
 *                               json (for verify pipeline),
 *                               raw (Phase 15 ui-map.v1.json node shape)
 *   --output         OPTIONAL — write to file (default: stdout)
 *
 * EXIT:
 *   0 — extraction successful (subtree may be empty if no matches)
 *   1 — invocation/precondition error (missing args, unparseable UI-MAP)
 *
 * Filter convention (per D-15 schema + D-12a/b ownership):
 *   - Node owns when node.owner_wave_id == target_wave AND
 *     (no owner-task-id filter OR node.owner_task_id == target_task).
 *   - Children inherit ownership unless they override with their own owner_*_id.
 *   - Subtree output preserves original tree shape; non-matching siblings
 *     are dropped, matching subtrees retained whole.
 */
import fs from "node:fs/promises"
import fsSync from "node:fs"
import path from "node:path"
import { parseArgs } from "node:util"

const HELP = `Usage: node extract-subtree-haiku.mjs [options]

  --uimap <path>           Path to planner UI-MAP.md
  --owner-wave-id <id>     Wave identifier to filter by (REQUIRED)
  --owner-task-id <id>     Optional task identifier (D-14 single-task scope)
  --format <fmt>           markdown | json | raw (default: markdown)
  --output <path>          Write to file (default: stdout)
  -h, --help               Show this help

Examples:
  # Extract wave-1 subtree as compact markdown for executor prompt
  node extract-subtree-haiku.mjs \\
      --uimap .vg/phases/7.14.3/UI-MAP.md \\
      --owner-wave-id wave-1

  # Extract single task subtree as JSON for diff
  node extract-subtree-haiku.mjs \\
      --uimap .vg/phases/7.14.3/UI-MAP.md \\
      --owner-wave-id wave-1 --owner-task-id T-3 \\
      --format json --output /tmp/subtree.json
`

function parseCli(argv) {
  const { values } = parseArgs({
    args: argv.slice(2),
    options: {
      uimap: { type: "string" },
      "owner-wave-id": { type: "string" },
      "owner-task-id": { type: "string" },
      format: { type: "string", default: "markdown" },
      output: { type: "string" },
      help: { type: "boolean", short: "h", default: false },
    },
    strict: true,
  })
  return values
}

function loadUiMap(uimapPath) {
  if (!fsSync.existsSync(uimapPath)) {
    console.error(`⛔ UI-MAP not found: ${uimapPath}`)
    process.exit(1)
  }
  const text = fsSync.readFileSync(uimapPath, "utf8")
  const m = text.match(/```json\s*\n([\s\S]*?)\n```/)
  if (!m) {
    console.error(`⛔ ${uimapPath}: no \`\`\`json\`\`\` code block found`)
    process.exit(1)
  }
  try {
    return JSON.parse(m[1])
  } catch (e) {
    console.error(`⛔ ${uimapPath}: JSON code block unparseable — ${e.message}`)
    process.exit(1)
  }
}

/**
 * Filter tree to subtree owned by target wave (+ optional task).
 * Returns null if neither node nor any descendant matches.
 *
 * Inheritance: when a node has owner_wave_id, descendants inherit unless
 * they override.
 */
function filterSubtree(node, targetWave, targetTask, inheritedWave, inheritedTask) {
  if (!node || typeof node !== "object") return null

  const wave = node.owner_wave_id || inheritedWave || null
  const task = node.owner_task_id || inheritedTask || null
  const waveMatch = wave === targetWave
  const taskMatch = !targetTask || task === targetTask
  const inScope = waveMatch && taskMatch

  const children = Array.isArray(node.children) ? node.children : []
  const keptChildren = []
  for (const c of children) {
    const kc = filterSubtree(c, targetWave, targetTask, wave, task)
    if (kc) keptChildren.push(kc)
  }

  if (!inScope && keptChildren.length === 0) return null
  return { ...node, children: keptChildren }
}

/**
 * Render subtree to compact markdown for Haiku/Sonnet prompt injection.
 * Format optimizes for token efficiency:
 *   - Indented hierarchy (2 spaces per depth)
 *   - 1 line per node: tag, key classes, props summary, text (if static)
 *   - Skip noise: empty classes, empty props_bound
 */
function renderMarkdown(node, depth = 0) {
  if (!node) return ""
  const indent = "  ".repeat(depth)
  const tag = node.tag || node.name || "?"
  const classes = (node.classes || []).slice(0, 4).join(" ")
  const propBindings = node.props_bound && typeof node.props_bound === "object"
    ? Object.keys(node.props_bound).slice(0, 3).join(",")
    : ""
  const text = node.text_content_static && node.text_content_static !== null
    ? ` "${String(node.text_content_static).slice(0, 60).replace(/\n/g, " ")}"`
    : ""
  const owner = node.owner_wave_id ? ` [${node.owner_wave_id}${node.owner_task_id ? "/" + node.owner_task_id : ""}]` : ""

  const parts = [`${indent}- \`${tag}\``]
  if (classes) parts.push(`.${classes.replace(/\s+/g, ".")}`)
  if (propBindings) parts.push(`[${propBindings}]`)
  if (text) parts.push(text)
  if (owner) parts.push(owner)

  let out = parts.join("") + "\n"
  const children = node.children || []
  for (const c of children) out += renderMarkdown(c, depth + 1)
  return out
}

async function main() {
  const values = parseCli(process.argv)
  if (values.help) {
    console.log(HELP)
    return
  }

  if (!values.uimap || !values["owner-wave-id"]) {
    console.error("⛔ --uimap and --owner-wave-id are required. Use --help for usage.")
    process.exit(1)
  }
  const validFormats = new Set(["markdown", "json", "raw"])
  if (!validFormats.has(values.format)) {
    console.error(`⛔ --format must be one of: ${[...validFormats].join(", ")}`)
    process.exit(1)
  }

  const data = loadUiMap(values.uimap)
  const root = data.root || data
  const subtree = filterSubtree(
    root,
    values["owner-wave-id"],
    values["owner-task-id"] || null,
    null, null,
  )

  if (!subtree) {
    console.error(
      `⚠ No nodes match owner-wave-id=${values["owner-wave-id"]}` +
      (values["owner-task-id"] ? ` + owner-task-id=${values["owner-task-id"]}` : "") +
      ` in ${values.uimap}. Empty subtree returned.`
    )
  }

  let output
  if (values.format === "raw") {
    output = JSON.stringify({
      version: data.version || "1",
      phase_id: data.phase_id,
      filter: {
        owner_wave_id: values["owner-wave-id"],
        owner_task_id: values["owner-task-id"] || null,
      },
      root: subtree || { tag: "(empty)", children: [] },
    }, null, 2)
  } else if (values.format === "json") {
    output = JSON.stringify(subtree || { tag: "(empty)", children: [] }, null, 2)
  } else {
    // markdown
    const header = `# UI-MAP subtree — ${values["owner-wave-id"]}` +
      (values["owner-task-id"] ? ` / ${values["owner-task-id"]}` : "") + "\n\n"
    const body = subtree ? renderMarkdown(subtree) : "_(no nodes match filter)_\n"
    output = header + body
  }

  if (values.output) {
    await fs.writeFile(values.output, output, "utf8")
    const lines = output.split("\n").length
    console.error(`✓ Subtree (${lines} lines) → ${values.output}`)
  } else {
    process.stdout.write(output)
  }
}

main().catch((err) => {
  console.error(`⛔ extract-subtree-haiku error: ${err.message}`)
  process.exit(1)
})
