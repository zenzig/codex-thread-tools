# Handoff Template

Use this structure when creating a handoff. Keep sections concise and delete sections that do not apply.

```markdown
# <Project/Task> Handoff - <YYYY-MM-DD>

## Resume Context

- Project: `<absolute project path>`
- Branch: `<branch name>`
- Thread/task: `<short description>`
- Current status: `<one sentence>`

## Goal

<What the next thread should accomplish next.>

## Decisions Made

- <Decision and rationale>
- <Decision and rationale>

## Current State

- Completed:
  - <completed item>
- In progress:
  - <current item>
- Not started:
  - <next item>

## Relevant Files

- `<path>`: <why it matters>
- `<path>`: <why it matters>

## Verification

- Ran: `<command>` -> <result>
- Not run: `<command>` -> <reason>

## Known Issues / Risks

- <specific risk, bug, failing test, or uncertainty>

## Assets / References

- `<path or URL>`: <why it matters>
- Archived visual manifest: `<absolute path to manifest.md>`: <why it matters>
- Archived visual JSON: `<absolute path to manifest.json>`: machine-readable archive inventory
- Archived visual file: `<absolute path to image/video>`: <visual context it preserves>

## Next Thread Prompt

Continue work in `<absolute project path>`.

Read this handoff first: `<absolute path to this file>`.

Then proceed with: <specific next action>.
```

If the prior thread had a crash, compaction failure, or context-window issue, add:

```markdown
## Codex Thread Notes

- Prior thread became too large to continue safely.
- Do not depend on loading the prior chat transcript.
- Use this handoff, git history, tests, and repo files as the source of truth.
```
