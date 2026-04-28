#!/bin/bash
# scaffold-penboard.sh — Phase 20 Tool B (PenBoard MCP)
# STUB for Wave A. Full automation deferred to Wave B / v2.17.0 (D-08).

scaffold_run() {
  echo "ℹ Tool B — PenBoard MCP."
  echo "  Wave B implementation (deferred to v2.17.0)."
  echo ""
  echo "  Workaround tạm: dùng Tool A (pencil-mcp) hoặc Tool C (ai-html)."
  echo ""
  echo "  Hoặc thủ công:"
  echo "  1. Mở PenBoard workspace existing OR tạo mới."
  echo "  2. Cho mỗi page: mcp__penboard__add_page → mcp__penboard__batch_design"
  echo "     hoặc design qua UI."
  echo "  3. Export workspace tới design_assets.paths/<workspace>.penboard"
  echo "  4. Re-run /vg:design-extract — handler penboard_mcp pickup."
  return 1
}
