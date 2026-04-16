# vN → vN+1 Migration

> Copy this template to `vN_to_vN+1.md` (e.g. `v1_to_v2.md`) when cutting a major release. `/vg:update --accept-breaking` will display this file before proceeding.

## Summary

One-paragraph description of what changed and why it's breaking.

## Breaking Changes

1. **[Change 1 title]**
   - **Before:** `config.old_key`
   - **After:** `config.new_key`
   - **Affects:** files `.claude/{path}` or user-facing command flag `--old-flag` → `--new-flag`
   - **Reason:** why this broke

2. **[Change 2 title]**
   - ...

## Automated Migration

If breaking change is mechanical (rename config key, rewrite file format), ship `scripts/migrate-vN-to-vN+1.py`:

```bash
# Auto-patch config + artifacts
python3 .claude/scripts/migrate-vN-to-vN+1.py

# Dry-run first
python3 .claude/scripts/migrate-vN-to-vN+1.py --dry-run
```

Omit this section if no automation available — user must migrate manually.

## Manual Migration

Steps user must do themselves:

1. **Update `.claude/vg.config.md`** — rename keys per breaking changes list
2. **Re-run `/vg:migrate {phase}`** for any phase created before vN+1 (if schema of phase artifacts changed)
3. **Review `.planning/` artifacts** for affected files
4. ...

## Rollback

If migration causes issues:

```bash
# Downgrade to previous version
/vg:update --version=vN.X.Y

# Restore ancestor from backup (ancestor dir auto-preserves)
cp -r .claude/vgflow-ancestor/vN.X.Y/* .claude/
echo "N.X.Y" > .claude/VGFLOW-VERSION
```

## Reference

- Issue: [link]
- PR: [link]
- Discussion: [link]
