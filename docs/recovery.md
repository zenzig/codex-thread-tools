# Recovery

Use recovery tools only after a thread is already hard to load, has disappeared
from the sidebar, or has hit a compaction/context error.

Start with inspection:

```bash
codex-thread-tools recover inspect ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

Before any repair, make a backup:

```bash
codex-thread-tools recover backup ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

## Safety Guards

The recovery tool is intentionally conservative:

- repair output cannot be written into `~/.codex/sessions/`
- live replacement requires `--replace-live`
- live replacement also requires `--confirm-replace-live` with the exact resolved path
- write operations refuse to run while Codex appears to be open

Treat repair commands as last-resort tools. Inspect first, back up before any
write, and prefer writing repaired output to a scratch path before replacing any
live session file.
