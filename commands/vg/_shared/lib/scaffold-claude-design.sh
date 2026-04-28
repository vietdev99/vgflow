#!/bin/bash
# scaffold-claude-design.sh — Phase 20 Tool D (gstack:design-shotgun)
# STUB for Wave A. Full integration deferred to Wave B / v2.17.0 (D-09).

scaffold_run() {
  echo "ℹ Tool D — Claude design (gstack:design-shotgun integration)."
  echo "  Wave B implementation (deferred to v2.17.0)."
  echo ""
  echo "  Workaround tạm — chạy gstack skill rồi quay lại:"
  echo ""
  echo "  1. /design-shotgun \"page slug, page type, description\""
  echo "     → gstack generate variants"
  echo "  2. User pick variant + iterate qua /design-shotgun --iterate"
  echo "  3. /design-html → finalize chosen variant tới HTML"
  echo "  4. Save HTML tới design_assets.paths/<slug>.html"
  echo "  5. Re-run /vg:design-scaffold --tool=manual-html (validate)"
  echo "     hoặc trực tiếp /vg:design-extract."
  echo ""
  echo "  Wave B sẽ wrap automatic — gstack skill availability detect +"
  echo "  spawn + auto-save chained."
  return 1
}
