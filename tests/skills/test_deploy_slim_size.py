"""Slim entry size guard — commands/vg/deploy.md MUST stay <= 500 lines."""
SLIM_LIMIT = 500


def test_deploy_md_within_slim_limit(skill_loader):
    skill = skill_loader("deploy")
    assert skill["lines"] <= SLIM_LIMIT, (
        f"commands/vg/deploy.md is {skill['lines']} lines (limit {SLIM_LIMIT}). "
        "Refactor Step 1 to spawn vg-deploy-executor instead of inline per-env loop, "
        "and push detail to commands/vg/_shared/deploy/."
    )
