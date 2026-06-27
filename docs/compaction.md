# Compaction

Codex can keep long conversations alive with several compaction systems. That
is useful, but it does not mean a single thread should be treated as the only
place your project memory lives.

## Paths

| Path | What it means |
| --- | --- |
| Local compaction | Codex creates a smaller replacement history locally and persists it into the session JSONL. |
| Remote compaction | Codex asks the remote compaction system to produce a smaller context window. |
| Remote compaction v2 / standalone compaction | A newer flow carries forward state with an opaque compaction output item from `/responses/compact`. |
| Server-side compaction | The Responses API can compact during normal response generation when configured with `context_management` and `compact_threshold`. |

In a local Codex session file, the strongest sign that compaction succeeded is a
JSONL record like:

```json
{
  "type": "compacted",
  "payload": {
    "replacement_history": []
  }
}
```

The important part is `payload.replacement_history`. That is the replacement
history Codex can use when rebuilding the live conversation. A `compacted`
record without a valid `replacement_history` is weaker and may be legacy or
malformed.

Remote compaction has a lifecycle:

1. A compaction request starts.
2. The request completes or fails.
3. The compacted result is installed as the live replacement history.

Step 2 by itself is not enough. A request can complete without becoming the
actual live conversation state. The important boundary is when the replacement
history is installed.

Server-side and standalone compaction can emit opaque encrypted compaction
items. Those items carry prior state forward with fewer tokens, but they are
intentionally not human-readable. They help Codex, but they are not durable
project notes for you.

## What Compaction Does Not Solve

Compaction reduces the context the model needs to see on later turns. It does
not solve every local thread failure mode.

A thread can still become unhealthy because:

- the session JSONL can keep growing on disk
- response and item counts can still approach API or app limits
- opaque compaction can preserve model-facing state without producing
  human-readable project notes
- failed compaction can leave a thread unable to continue cleanly
- legacy or malformed compacted records may not reconstruct well
- Codex may still struggle to load a very large session file

That is why this repo uses health checks, handoffs, and archive tools together.
