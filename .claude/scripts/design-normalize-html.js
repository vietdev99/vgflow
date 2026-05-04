#!/usr/bin/env node
/**
 * HTML prototype → screenshot + cleaned HTML + interactions list.
 *
 * Called from design-normalize.py via subprocess.
 * Uses npx playwright (already installed).
 *
 * Usage:
 *   node design-normalize-html.js <input.html> <output_dir> <slug> [--states]
 *
 * Output files:
 *   <output_dir>/screenshots/<slug>.default.png
 *   <output_dir>/screenshots/<slug>.<state-id>.png  (if --states, per trigger)
 *   <output_dir>/refs/<slug>.structural.html
 *   <output_dir>/refs/<slug>.interactions.md
 *   <output_dir>/refs/<slug>.states.json
 *
 * Emits JSON result to stdout (for Python to parse):
 *   { "slug": "...", "screenshots": [...], "structural": "...", "interactions": "...", "states": [...] }
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

// Phase 15 D-01 — cheerio AST output. Lazy-required so script still runs if
// cheerio not installed (downgrades to no-AST mode + warning in result).
let cheerio = null;
try { cheerio = require('cheerio'); } catch (_) { /* optional dep */ }

// ---------------------------------------------------------------------------
// Cleaned HTML extraction
// ---------------------------------------------------------------------------

async function extractCleanedHtml(page) {
  return await page.evaluate(() => {
    // Clone the document so we don't mutate live DOM.
    const root = document.documentElement.cloneNode(true);
    // Remove noisy content but keep structure + attributes.
    root.querySelectorAll('script').forEach(el => {
      // Replace body with comment note; executor doesn't need JS code but needs to know handlers exist.
      el.textContent = '/* script body elided — see interactions.md */';
    });
    root.querySelectorAll('style').forEach(el => {
      el.textContent = '/* style body elided — preserve class references */';
    });
    root.querySelectorAll('link[rel="stylesheet"]').forEach(el => el.remove());
    root.querySelectorAll('meta').forEach(el => el.remove());
    // Keep class, id, data-*, onclick, onchange, href, src (structural + behavioral signals).
    return '<!DOCTYPE html>\n' + root.outerHTML;
  });
}

// ---------------------------------------------------------------------------
// Phase 15 D-01 — Cheerio AST extraction for structural diff
// ---------------------------------------------------------------------------
//
// Walks the cleaned HTML DOM via cheerio and emits a unified node tree that
// matches schemas/structural-json.v1.json. Compared by drift validators
// (verify-ui-structure.py wave-scoped + verify-holistic-drift.py) against
// generate-ui-map.mjs as-built scan.

function extractStructuralAst(cleanedHtml) {
  if (!cheerio) {
    return null; // caller emits warning in result payload
  }
  const $ = cheerio.load(cleanedHtml);

  function walk(el) {
    const $el = $(el);
    const tag = (el.tagName || el.name || 'unknown').toLowerCase();
    const classAttr = $el.attr('class') || '';
    const classes = classAttr.trim() ? classAttr.trim().split(/\s+/) : [];
    const role = $el.attr('role') || null;

    // Static text content: only when el has direct text + no element children.
    // (Otherwise text is mixed with descendants — leave as null = dynamic.)
    const directText = $el.contents()
      .filter(function () { return this.type === 'text'; })
      .text()
      .trim();
    const hasElementChildren = $el.children().length > 0;
    const text = (directText && !hasElementChildren) ? directText : null;

    // Props: data-* + aria-* + name/href/src + onclick markers
    const props = {};
    if (el.attribs) {
      for (const [k, v] of Object.entries(el.attribs)) {
        if (k === 'class' || k === 'style') continue;
        if (k.startsWith('data-') || k.startsWith('aria-') ||
            ['id', 'name', 'href', 'src', 'type', 'value', 'placeholder'].includes(k) ||
            k.startsWith('on')) {
          props[k] = v;
        }
      }
    }

    const children = [];
    $el.children().each((_, child) => { children.push(walk(child)); });

    return { tag, classes, role, text, props, children };
  }

  // Start from <body> if present (skips <html>/<head> noise), else root.
  const bodyEl = $('body').get(0);
  const rootEl = bodyEl || $.root().children().get(0);
  if (!rootEl) return null;

  return {
    format_version: '1.0',
    source_format: 'html',
    extracted_at: new Date().toISOString(),
    root: walk(rootEl),
  };
}

// ---------------------------------------------------------------------------
// Interactions extraction
// ---------------------------------------------------------------------------

async function extractInteractions(page) {
  return await page.evaluate(() => {
    const interactions = [];

    // Inline handlers: onclick, onchange, onsubmit, etc.
    const eventAttrs = ['onclick', 'onchange', 'onsubmit', 'oninput', 'onblur', 'onfocus',
                        'onmouseover', 'onmouseout', 'onkeydown', 'onkeyup'];
    document.querySelectorAll('*').forEach(el => {
      eventAttrs.forEach(attr => {
        const code = el.getAttribute(attr);
        if (code) {
          interactions.push({
            type: 'inline-handler',
            event: attr.replace(/^on/, ''),
            selector: el.tagName.toLowerCase() +
                      (el.id ? `#${el.id}` : '') +
                      (el.className ? '.' + String(el.className).trim().split(/\s+/).slice(0, 2).join('.') : ''),
            text: (el.textContent || '').trim().slice(0, 60),
            code: code.slice(0, 200),
          });
        }
      });
    });

    // Trigger hints: buttons + links + things with data-action/data-bs-toggle/etc.
    const triggers = [];
    const triggerSelectors = [
      'button', 'a[href^="#"]',
      '[data-action]', '[data-bs-toggle]', '[data-toggle]', '[data-target]',
      '[role="button"]', '[role="tab"]',
    ];
    document.querySelectorAll(triggerSelectors.join(', ')).forEach(el => {
      const text = (el.textContent || '').trim().slice(0, 40);
      const id = el.id || null;
      const cls = el.className || '';
      const dataAttrs = {};
      for (const a of el.attributes) {
        if (a.name.startsWith('data-')) dataAttrs[a.name] = a.value;
      }
      triggers.push({
        tag: el.tagName.toLowerCase(),
        id,
        class: cls,
        text,
        dataAttrs,
      });
    });

    return { inlineHandlers: interactions, triggers };
  });
}

// ---------------------------------------------------------------------------
// State capture (click triggers, screenshot)
// ---------------------------------------------------------------------------

async function captureStates(page, outputDir, slug, maxStates = 6) {
  const screenshots = [];
  const states = [];

  const triggers = await page.evaluate(() => {
    const sel = 'button, a[href^="#"], [data-action], [data-bs-toggle], [role="tab"], [role="button"]';
    return Array.from(document.querySelectorAll(sel)).slice(0, 20).map((el, i) => ({
      index: i,
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      text: (el.textContent || '').trim().slice(0, 40),
      selector: `${el.tagName.toLowerCase()}:nth-of-type(${i + 1})`,
    }));
  });

  let captured = 0;
  for (const trigger of triggers) {
    if (captured >= maxStates) break;
    try {
      // Use index-based locator: grab the i-th matching trigger
      const handle = await page.$$eval(
        'button, a[href^="#"], [data-action], [data-bs-toggle], [role="tab"], [role="button"]',
        (els, idx) => els[idx] ? els[idx].outerHTML : null,
        trigger.index
      );
      if (!handle) continue;

      const locator = page.locator(
        'button, a[href^="#"], [data-action], [data-bs-toggle], [role="tab"], [role="button"]'
      ).nth(trigger.index);

      // Click with short timeout; catch nav/errors silently
      await locator.click({ timeout: 2000 }).catch(() => {});
      await page.waitForTimeout(400);  // let UI settle

      const stateSlug = `trigger-${trigger.index}-${(trigger.text || 'unnamed').replace(/[^a-z0-9]/gi, '_').toLowerCase().slice(0, 20)}`;
      const screenshotPath = path.join(outputDir, 'screenshots', `${slug}.${stateSlug}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true });

      screenshots.push(path.relative(outputDir, screenshotPath));
      states.push({ ...trigger, state: stateSlug, screenshot: path.relative(outputDir, screenshotPath) });
      captured++;

      // Dismiss any modal/overlay before next trigger: press Escape + click body.
      await page.keyboard.press('Escape').catch(() => {});
      await page.mouse.click(10, 10).catch(() => {});
      await page.waitForTimeout(200);
    } catch (err) {
      // Skip silently; it's OK for some triggers to fail.
    }
  }

  return { screenshots, states };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const args = process.argv.slice(2);
  const inputPath = args[0];
  const outputDir = args[1];
  const slug = args[2];
  const captureStatesFlag = args.includes('--states');

  if (!inputPath || !outputDir || !slug) {
    console.error('Usage: node design-normalize-html.js <input> <output_dir> <slug> [--states]');
    process.exit(1);
  }

  const screenshotsDir = path.join(outputDir, 'screenshots');
  const refsDir = path.join(outputDir, 'refs');
  fs.mkdirSync(screenshotsDir, { recursive: true });
  fs.mkdirSync(refsDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  const fileUrl = 'file://' + path.resolve(inputPath).replace(/\\/g, '/');

  try {
    await page.goto(fileUrl, { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);

    const result = {
      slug,
      handler: 'playwright_render',
      screenshots: [],
      structural: null,
      structural_json: null, // Phase 15 D-01 — cheerio AST output path
      interactions: null,
      states: [],
    };

    // Default full-page screenshot
    const defaultPng = path.join(screenshotsDir, `${slug}.default.png`);
    await page.screenshot({ path: defaultPng, fullPage: true });
    result.screenshots.push(path.relative(outputDir, defaultPng));

    // Cleaned HTML
    const cleanedHtml = await extractCleanedHtml(page);
    const structuralPath = path.join(refsDir, `${slug}.structural.html`);
    fs.writeFileSync(structuralPath, cleanedHtml, 'utf-8');
    result.structural = path.relative(outputDir, structuralPath);

    // Phase 15 D-01 — Cheerio AST → structural.json
    const ast = extractStructuralAst(cleanedHtml);
    if (ast) {
      const astPath = path.join(refsDir, `${slug}.structural.json`);
      ast.source_path = inputPath;
      fs.writeFileSync(astPath, JSON.stringify(ast, null, 2), 'utf-8');
      result.structural_json = path.relative(outputDir, astPath);
    } else {
      result.warning = (result.warning ? result.warning + '; ' : '') +
        'cheerio not installed — structural.json AST not emitted (run: npm i cheerio in vgflow-repo to enable)';
    }

    // Interactions
    const interactions = await extractInteractions(page);
    let interactionsMd = `# Interactions — ${slug}\n\nExtracted from: ${inputPath}\n\n`;
    interactionsMd += `## Inline handlers (${interactions.inlineHandlers.length})\n\n`;
    for (const h of interactions.inlineHandlers) {
      interactionsMd += `- **${h.event}** on \`${h.selector}\`${h.text ? ` ("${h.text}")` : ''}\n`;
      interactionsMd += `  \`\`\`js\n  ${h.code}\n  \`\`\`\n`;
    }
    interactionsMd += `\n## Triggers discovered (${interactions.triggers.length})\n\n`;
    for (const t of interactions.triggers.slice(0, 50)) {
      const dataAttrStr = Object.keys(t.dataAttrs).length
        ? ` [${Object.entries(t.dataAttrs).map(([k, v]) => `${k}="${v}"`).join(' ')}]`
        : '';
      interactionsMd += `- \`<${t.tag}${t.id ? ` id="${t.id}"` : ''}>${dataAttrStr}\` — "${t.text}"\n`;
    }
    const interactionsPath = path.join(refsDir, `${slug}.interactions.md`);
    fs.writeFileSync(interactionsPath, interactionsMd, 'utf-8');
    result.interactions = path.relative(outputDir, interactionsPath);

    // Optional state capture
    if (captureStatesFlag) {
      const statesResult = await captureStates(page, outputDir, slug, 6);
      result.screenshots.push(...statesResult.screenshots);
      result.states = statesResult.states;

      const statesJsonPath = path.join(refsDir, `${slug}.states.json`);
      fs.writeFileSync(statesJsonPath, JSON.stringify(statesResult.states, null, 2));
    }

    console.log(JSON.stringify(result));
    process.exit(0);
  } catch (err) {
    console.error(JSON.stringify({ error: String(err && err.message || err), slug, handler: 'playwright_render' }));
    process.exit(2);
  } finally {
    await browser.close();
  }
}

main();
