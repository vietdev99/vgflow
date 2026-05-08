# Publishing vgflow to npm

## Pre-flight checklist

```bash
# 1. Verify npm login
npm whoami    # should print your username, not 401

# 2. Verify name available (only matters first publish)
npm view vgflow    # 404 = available, else taken

# 3. Verify VERSION + package.json sync
cat VERSION
cat package.json | grep '"version"'
# Both must match

# 4. Verify required files exist
ls bin/vg.js bin/vg-cli-dispatcher.sh VERSION LICENSE README.md
```

## First publish (one-time)

```bash
# 1. Login (interactive — browser flow)
npm login

# 2. Verify scope (public)
npm config get access    # should be public OR set in package.json publishConfig

# 3. Dry-run pack to inspect contents
npm pack --dry-run
# Verify: ~6-7 MB, includes bin/, commands/, scripts/, skills/, schemas/, templates/, codex-skills/
# Verify: NO .git/, .vg/, .claude/, tests/, dev-phases/

# 4. Test pack locally
npm pack
# Output: vgflow-{VERSION}.tgz

# 5. Test install global (locally)
npm install -g ./vgflow-{VERSION}.tgz
vg version    # should print VERSION
vg doctor     # should report install location
vg help       # should print full command list

# 6. Uninstall local test
npm uninstall -g vgflow

# 7. Publish public
npm publish --access=public
# OR (if publishConfig in package.json):
npm publish

# 8. Verify
npm view vgflow
# Should show: latest, version, dist-tags
```

## Subsequent publishes (per release)

```bash
# 1. Update VERSION + package.json (must match)
echo "2.53.0" > VERSION
node -e '
const fs = require("fs");
const v = fs.readFileSync("VERSION", "utf8").trim();
const p = JSON.parse(fs.readFileSync("package.json", "utf8"));
p.version = v;
fs.writeFileSync("package.json", JSON.stringify(p, null, 2) + "\n");
'

# 2. Commit + tag (existing release flow)
git add VERSION VGFLOW-VERSION .claude/VGFLOW-VERSION package.json CHANGELOG.md
git commit -m "release: v2.53.0"
git tag v2.53.0

# 3. Push (triggers github-actions release tarball auto-create)
git push origin main
git push origin v2.53.0

# 4. Publish to npm
npm publish
# prepublishOnly script runs scripts/npm-prepublish-check.js automatically
# Aborts if VERSION ≠ package.json version

# 5. Verify
npm view vgflow versions    # should include 2.53.0
npm view vgflow@latest      # should show 2.53.0
```

## Test global install (clean machine)

```bash
# On a fresh machine or in a test container:
npm install -g vgflow

# postinstall prints next-step prompt:
#   vgflow 2.53.0
#   Installed at: /path/to/npm/lib/node_modules/vgflow
#   Next steps: vg install / vg help / vg doctor

# Wire hooks:
vg install --global    # writes ~/.claude/settings.json with VG entries
vg doctor              # verify

# In a project:
cd /path/to/project
vg install --project   # OR keep --global; project marker auto-set on first use
```

## Unpublish (if disaster)

```bash
# Within 72h of publish:
npm unpublish vgflow@2.53.0

# After 72h: cannot unpublish, must publish a patched version
# (this is npm policy, not VG specific)
```

## Deprecation (graceful)

```bash
npm deprecate vgflow@<2.50.0 "Upgrade to v2.50+ — see CHANGELOG for breaking changes"
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `npm publish` 403 Forbidden | Check `npm whoami`, verify package access (public/restricted) |
| `npm publish` E402 (paid registry) | Add `--access=public` flag or set `publishConfig.access` in package.json |
| `prepublishOnly` script fails | VERSION ≠ package.json version. Re-sync. |
| Postinstall prints but doesn't wire hooks | Conservative-by-design. Run `vg install` explicitly. |
| Windows install fails to find bash | Set `VG_BASH=/c/Program Files/Git/bin/bash.exe` in env. Or install Git for Windows. |

## CI/CD integration

GitHub Actions example for auto-publish on tag push:

```yaml
name: npm-publish
on:
  push:
    tags: ['v*']
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          registry-url: 'https://registry.npmjs.org'
      - run: npm publish
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

Setup:
1. `npm token create` — generate publish token at npmjs.com
2. GitHub repo settings → Secrets → add `NPM_TOKEN`
3. Push next tag → auto-publish

## Versioning policy

- `package.json.version` = `VERSION` file = git tag (without `v` prefix)
- Patch (`x.y.Z`): bug fixes, no API changes
- Minor (`x.Y.z`): new features, backwards compat
- Major (`X.y.z`): breaking changes (e.g., v3.0.0 = global install layout)

## Links

- npm registry: https://www.npmjs.com/package/vgflow (after first publish)
- npm token management: https://www.npmjs.com/settings/{username}/tokens
- 2FA setup: https://docs.npmjs.com/configuring-two-factor-authentication
