from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "codex-thread-handoff"


def test_handoff_skill_uses_deferred_workflow_reference() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert len(skill.splitlines()) <= 55
    assert "references/handoff-workflow.md" in skill
    assert "references/handoff-template.md" in skill


def test_handoff_workflow_requires_visual_archive_decision() -> None:
    workflow = (SKILL_ROOT / "references" / "handoff-workflow.md").read_text(
        encoding="utf-8"
    )
    template = (SKILL_ROOT / "references" / "handoff-template.md").read_text(
        encoding="utf-8"
    )

    assert "Do not silently omit visual handling" in workflow
    assert "Archived:" in workflow
    assert "Not archived:" in workflow
    assert "## Visual Archive Decision" in template


def test_handoff_workflow_records_sidecar_marker_and_prompt_marker() -> None:
    workflow = (SKILL_ROOT / "references" / "handoff-workflow.md").read_text(
        encoding="utf-8"
    )

    assert "tools/codex-thread-handoff-marker.py record" in workflow
    assert "Codex thread handoff marker:" in workflow


def test_handoff_workflow_can_seed_redacted_summary() -> None:
    workflow = (SKILL_ROOT / "references" / "handoff-workflow.md").read_text(
        encoding="utf-8"
    )

    assert "tools/codex-thread-handoff-summary.py" in workflow
    assert "Do not dump raw transcript or tool payloads" in workflow


def test_compaction_docs_use_current_openai_compaction_terms() -> None:
    compaction_docs = (ROOT / "docs" / "compaction.md").read_text(encoding="utf-8")

    assert "context_management" in compaction_docs
    assert "compact_threshold" in compaction_docs
    assert "/responses/compact" in compaction_docs
    assert "opaque encrypted compaction" in compaction_docs
    assert "replacement_history" in compaction_docs
