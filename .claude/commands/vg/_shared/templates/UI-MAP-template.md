# UI Component Map — Phase {PHASE_NUMBER}

**Mục đích:** Cây component đích cho các view mới/sửa trong phase này. Executor
MUST bám theo cấu trúc trong phần JSON (machine-readable) khi viết code.
verify-ui-structure.py sẽ so sánh cây thực tế post-wave vs phần JSON này để phát
hiện lệch (drift).

**Quy tắc điền:**
1. Với MỖI view trong phase, tạo 1 section `## View: <TênComponent>`
2. Viết cây ASCII (người đọc) + block JSON tree (máy so sánh)
3. Component node phải ghi: `name`, `file` (đường dẫn đích), `layout` (class layout dự kiến)
4. Thứ tự children trong JSON là thứ tự render kỳ vọng (top → bottom, left → right)
5. Nếu sửa view đã có, copy từ `UI-MAP-AS-IS.md` rồi annotate thêm/xoá

---

## View: DealsListPage (ví dụ)

**File:** `apps/web/src/pages/admin/deals/DealsListPage.tsx`
**Liên kết goal:** G-01, G-04

### Cây ASCII (người đọc)

```
[DealsListPage] - apps/web/src/pages/admin/deals/DealsListPage.tsx (space-y-6)
└── [div] (space-y-6)
    ├── [div] (flex items-start justify-between gap-4)
    │   ├── [PageHeader] - components/shared/PageHeader.tsx
    │   │   └── "Deals"
    │   └── [Button] - components/ui/button.tsx
    │       └── "Create Deal"
    ├── [DataTable] - components/shared/DataTable.tsx
    │   ├── [TableFilters] (flex gap-2)
    │   └── [TableBody]
    └── [ConfirmDialog] - components/shared/ConfirmDialog.tsx
```

### JSON tree (machine-readable, dùng cho diff)

```json
{
  "kind": "component",
  "name": "DealsListPage",
  "file": "apps/web/src/pages/admin/deals/DealsListPage.tsx",
  "layout": "space-y-6",
  "children": [
    {
      "kind": "framework",
      "name": "div",
      "layout": "space-y-6",
      "children": [
        {
          "kind": "framework",
          "name": "div",
          "layout": "flex items-start justify-between gap-4",
          "children": [
            {
              "kind": "component",
              "name": "PageHeader",
              "file": "components/shared/PageHeader.tsx"
            },
            {
              "kind": "component",
              "name": "Button",
              "file": "components/ui/button.tsx"
            }
          ]
        },
        {
          "kind": "component",
          "name": "DataTable",
          "file": "components/shared/DataTable.tsx"
        },
        {
          "kind": "component",
          "name": "ConfirmDialog",
          "file": "components/shared/ConfirmDialog.tsx"
        }
      ]
    }
  ]
}
```

### Ghi chú (notes)
- `PageHeader` có 2 props: `title` (string), `action` (ReactNode) — pass Button vào
- `DataTable` generic `<Deal>` với columns: id, type, status, floor, advertiser
- `ConfirmDialog` open qua state `deleteId` (string | null)

---

_Template note: xoá section ví dụ này khi viết UI-MAP.md thực tế._
