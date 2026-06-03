# Codex Thread Handoff Workflow

1. Inspect: capture project root, `git status --short`, `git log --oneline -8`, and only relevant diffs. Do not revert unrelated user work.

2. Health: run `python3 tools/codex-thread-health.py` when available. Codes `0`/`2`/`3` mean `OK`/`WARN`/`DANGER`. Include status, continuation health, handoff readiness, recommendation, top reasons, and domain risks. Do not use `--safe-test-mode` on live sessions.

3. Visuals: if visuals are reported or mentioned, scan known sessions with `tools/codex-visual-archive.py scan <session-file>`. To retain visuals, ask for archive location, then use `wizard` or `archive`. If the session is unknown and visuals matter, ask for the exact session path.

Record one visual outcome:
- `Archived:` with absolute paths to `manifest.md`, `manifest.json`, `handoff-snippet.md`, and important files.
- `Not archived:` with the concrete reason.

Do not silently omit visual handling when visual references exist. Do not embed base64 media.

4. Write: prefer `documentation/agent-handoffs/`, `docs/handoffs/`, or `notes/handoffs/`; otherwise create `documentation/agent-handoffs/`. Use `YYYY-MM-DD-short-topic.md` and `references/handoff-template.md`. Include concrete paths, branch, next action, decisions, relevant files, verification, risks, health readiness, and visual archive decision.

5. Mark: after verifying the handoff file, run `python3 tools/codex-thread-handoff-marker.py record --source-session-file <session-file> --handoff-file <handoff-file>`. Add the printed `Codex thread handoff marker:` block to `Next Thread Prompt`.

6. Finish: verify readability. Report the path, git state, marker file, and exact prompt.
