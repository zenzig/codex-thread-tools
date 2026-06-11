from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-npm.yml"


def test_npm_publish_workflow_is_release_gated() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    assert "  release:\n    types: [published]" in workflow_text
    assert "  workflow_dispatch:" in workflow_text
    assert "  push:" not in workflow_text
    assert "permissions:\n  contents: read\n  id-token: write" in workflow_text


def test_npm_publish_workflow_verifies_and_publishes_package() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    assert "publish-npm:" in workflow_text
    assert "actions/checkout@v6" in workflow_text
    assert "actions/setup-node@v6" in workflow_text
    assert 'node-version: "24"' in workflow_text
    assert "package-manager-cache: false" in workflow_text
    assert "npm install -g npm@latest" in workflow_text
    assert "python3 -m pytest" in workflow_text
    assert "npm pack --dry-run" in workflow_text
    assert "npm publish --provenance --access public" in workflow_text
    assert "secrets.NPM_TOKEN" not in workflow_text
    assert "NODE_AUTH_TOKEN" not in workflow_text
    assert "VERSION" in workflow_text
    assert "package.json" in workflow_text
    assert "github.event.release.tag_name" in workflow_text
