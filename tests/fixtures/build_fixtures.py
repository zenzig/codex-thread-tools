#!/usr/bin/env python3
"""Build deterministic Codex session JSONL fixtures for tests."""

from __future__ import annotations

import json
import base64
from pathlib import Path


ROOT = Path(__file__).resolve().parent / "sessions"
VISUAL_ROOT = Path(__file__).resolve().parent / "visual_assets"
# Fixed timestamps keep generated session fixtures deterministic.
TS = "2026-05-24T12:00:00Z"
TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
TINY_PNG_BYTES = base64.b64decode(TINY_PNG_BASE64)
TINY_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def session_meta(session_id: str, cwd: str) -> dict:
    return {
        "timestamp": TS,
        "type": "session_meta",
        "payload": {"id": session_id, "cwd": cwd},
    }


def turn_context(cwd: str) -> dict:
    return {
        "timestamp": TS,
        "type": "turn_context",
        "payload": {"cwd": cwd, "model": "gpt-5.5"},
    }


def message(role: str, text: str, ts: str = TS) -> dict:
    content_type = "input_text" if role == "user" else "output_text"
    return {
        "timestamp": ts,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": content_type, "text": text}],
        },
    }


def event(event_type: str, message_text: str, ts: str = TS) -> dict:
    return {
        "timestamp": ts,
        "type": "event_msg",
        "payload": {"type": event_type, "message": message_text},
    }


def token_count(total_tokens: int, last_tokens: int, context_window: int, ts: str = TS) -> dict:
    return {
        "timestamp": ts,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total_tokens,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": total_tokens,
                },
                "last_token_usage": {
                    "input_tokens": last_tokens,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": last_tokens,
                },
                "model_context_window": context_window,
            },
        },
    }


def compaction_item(kind: str = "compaction", ts: str = TS) -> dict:
    payload = {"type": kind, "encrypted_content": "opaque-state"}
    if kind == "context_compaction":
        payload = {"type": kind, "id": "ctx-1"}
    return {"timestamp": ts, "type": "response_item", "payload": payload}


def compacted_record(message_text: str, replacement_count: int, ts: str = TS) -> dict:
    replacement_history = [
        {
            "type": "message",
            "role": "user" if index % 2 == 0 else "assistant",
            "content": [{"type": "input_text", "text": f"retained {index}"}],
        }
        for index in range(replacement_count)
    ]
    return {
        "timestamp": ts,
        "type": "compacted",
        "payload": {
            "message": message_text,
            "replacement_history": replacement_history,
        },
    }


def healthy() -> list[dict]:
    records = [session_meta("healthy", "/work/project-a"), turn_context("/work/project-a")]
    for index in range(4):
        records.append(message("user", f"request {index}"))
        records.append(message("assistant", f"answer {index}"))
        records.append(event("user_message", f"request {index}"))
        records.append(event("agent_message", f"answer {index}"))
    return records


def compaction_success() -> list[dict]:
    records = [session_meta("compaction-success", "/work/project-b"), turn_context("/work/project-b")]
    records.extend(message("user", f"task {index}") for index in range(8))
    records.append({"timestamp": TS, "type": "response_item", "payload": {"type": "compaction_trigger"}})
    records.append(compaction_item("context_compaction"))
    records.append(compaction_item("compaction"))
    records.append(compacted_record("summary after compaction", 4))
    records.append(event("context_compacted", "context compacted"))
    records.append(event("turn_complete", "turn complete"))
    return records


def compaction_failed() -> list[dict]:
    records = [session_meta("compaction-failed", "/work/project-c"), turn_context("/work/project-c")]
    records.extend(message("user", f"large task {index}") for index in range(12))
    records.append({"timestamp": TS, "type": "response_item", "payload": {"type": "compaction_trigger"}})
    records.append(
        event(
            "warning",
            "remote compaction v2 expected exactly one compaction output item, got 0",
        )
    )
    records.append(event("error", "maximum length 16384, got 30351"))
    records.append(event("turn_aborted", "turn aborted"))
    return records


def many_compactions() -> list[dict]:
    records = [session_meta("many-compactions", "/work/project-d"), turn_context("/work/project-d")]
    for index in range(6):
        records.append(message("user", f"task {index}"))
        records.append(compaction_item("compaction"))
        records.append(compacted_record(f"summary {index}", 3))
    records.append(
        event(
            "warning",
            "Heads up: Long threads and multiple compactions can cause the model to be less accurate.",
        )
    )
    return records


def discussion_only() -> list[dict]:
    records = [session_meta("discussion-only", "/work/project-e"), turn_context("/work/project-e")]
    records.append(message("user", "Please write an article about remote compaction failed errors."))
    records.append(message("assistant", "The phrase maximum length 16384 is only article text here."))
    records.append(event("turn_complete", "turn complete"))
    records.append(token_count(total_tokens=250_000, last_tokens=20_000, context_window=258_400))
    return records


def token_cumulative_high() -> list[dict]:
    records = [
        session_meta("token-cumulative-high", "/work/project-f"),
        turn_context("/work/project-f"),
        message("user", "Continue the task."),
        message("assistant", "Still healthy."),
        token_count(total_tokens=2_000_000, last_tokens=40_000, context_window=258_400),
        event("turn_complete", "turn complete"),
    ]
    return records


def token_cumulative_older_same_project() -> list[dict]:
    ts = "2026-05-23T12:00:00Z"
    return [
        session_meta("token-cumulative-older", "/work/project-f"),
        turn_context("/work/project-f"),
        message("user", "Earlier related task.", ts=ts),
        token_count(
            total_tokens=100_000,
            last_tokens=5_000,
            context_window=258_400,
            ts=ts,
        ),
        event("turn_complete", "turn complete", ts=ts),
    ]


def token_multiple_events() -> list[dict]:
    first_ts = "2026-05-24T11:00:00Z"
    return [
        session_meta("token-multiple-events", "/work/project-j"),
        turn_context("/work/project-j"),
        message("user", "First turn.", ts=first_ts),
        token_count(
            total_tokens=1_000,
            last_tokens=1_000,
            context_window=258_400,
            ts=first_ts,
        ),
        message("assistant", "Second turn."),
        token_count(total_tokens=3_000, last_tokens=2_000, context_window=258_400),
        event("turn_complete", "turn complete"),
    ]


def event_failure() -> list[dict]:
    records = [
        session_meta("event-failure", "/work/project-g"),
        turn_context("/work/project-g"),
        message("user", "Start a large task."),
        {"timestamp": TS, "type": "response_item", "payload": {"type": "compaction_trigger"}},
        event("error", "remote compaction failed before installing replacement history"),
        event("turn_aborted", "turn aborted"),
    ]
    return records


def event_aliases() -> list[dict]:
    return [
        session_meta("event-aliases", "/work/project-h"),
        turn_context("/work/project-h"),
        event("task_started", "turn started"),
        message("user", "Do a small task."),
        message("assistant", "Done."),
        event("task_complete", "turn complete"),
    ]


def runtime_error() -> list[dict]:
    return [
        session_meta("runtime-error", "/work/project-i"),
        turn_context("/work/project-i"),
        message("user", "Run the shell command."),
        event("error", "subprocess exited with code 1"),
        event("turn_aborted", "turn aborted"),
    ]


def write_visual_assets() -> dict[str, Path]:
    VISUAL_ROOT.mkdir(parents=True, exist_ok=True)
    tiny_png = VISUAL_ROOT / "tiny.png"
    tiny_copy = VISUAL_ROOT / "tiny copy.png"
    tiny_mp4 = VISUAL_ROOT / "tiny.mp4"
    outside = VISUAL_ROOT.parent / "outside-visual.png"
    escaped = VISUAL_ROOT / "escaped.png"
    tiny_png.write_bytes(TINY_PNG_BYTES)
    tiny_copy.write_bytes(TINY_PNG_BYTES)
    tiny_mp4.write_bytes(TINY_MP4_BYTES)
    outside.write_bytes(TINY_PNG_BYTES)
    if escaped.exists() or escaped.is_symlink():
        escaped.unlink()
    try:
        escaped.symlink_to(Path("..") / outside.name)
    except OSError:
        escaped.write_text(str(outside), encoding="utf-8")
    return {
        "tiny_png": tiny_png,
        "tiny_copy": tiny_copy,
        "tiny_mp4": tiny_mp4,
        "missing_png": VISUAL_ROOT / "missing.png",
        "escaped": escaped,
    }


def image_message(session_id: str, cwd: str, content: list[dict]) -> list[dict]:
    return [
        session_meta(session_id, cwd),
        turn_context(cwd),
        {
            "timestamp": TS,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": content,
            },
        },
    ]


def visual_embedded_image(_assets: dict[str, Path]) -> list[dict]:
    return image_message(
        "visual-embedded-image",
        "/work/project-visual",
        [{"type": "input_image", "image_url": f"data:image/png;base64,{TINY_PNG_BASE64}"}],
    )


def visual_local_images_event(assets: dict[str, Path]) -> list[dict]:
    return [
        session_meta("visual-local-images-event", "/work/project-visual"),
        turn_context("/work/project-visual"),
        {
            "timestamp": TS,
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": "attached a screenshot",
                "local_images": [str(assets["tiny_png"])],
            },
        },
    ]


def visual_markdown_paths(assets: dict[str, Path]) -> list[dict]:
    text = (
        f"Primary screenshot: ![layout]({assets['tiny_png']})\n"
        f"Spaced path: ![colors]({assets['tiny_copy']})\n"
        f"Raw path: {assets['tiny_png']}\n"
        "Relative reference: ./not-copied.png"
    )
    return image_message(
        "visual-markdown-paths",
        "/work/project-visual",
        [{"type": "input_text", "text": text}],
    )


def visual_video_reference(assets: dict[str, Path]) -> list[dict]:
    video_b64 = base64.b64encode(TINY_MP4_BYTES).decode("ascii")
    return image_message(
        "visual-video-reference",
        "/work/project-visual",
        [
            {"type": "input_video", "video_url": f"data:video/mp4;base64,{video_b64}"},
            {"type": "input_text", "text": f"Motion reference: {assets['tiny_mp4']}"},
        ],
    )


def visual_duplicates(assets: dict[str, Path]) -> list[dict]:
    return image_message(
        "visual-duplicates",
        "/work/project-visual",
        [
            {"type": "input_image", "image_url": f"data:image/png;base64,{TINY_PNG_BASE64}"},
            {"type": "input_image", "image_url": f"data:image/png;base64,{TINY_PNG_BASE64}"},
            {"type": "input_text", "text": f"{assets['tiny_png']}\n{assets['tiny_png']}"},
        ],
    )


def visual_malformed_and_missing(assets: dict[str, Path]) -> list[dict]:
    return image_message(
        "visual-malformed-and-missing",
        "/work/project-visual",
        [
            {"type": "input_image", "image_url": "data:image/png;base64,this-is-not-valid"},
            {"type": "input_text", "text": f"Missing: {assets['missing_png']}"},
            {"type": "input_text", "text": "Remote: https://example.com/not-archived.png"},
        ],
    )


def visual_symlink_escape(assets: dict[str, Path]) -> list[dict]:
    return image_message(
        "visual-symlink-escape",
        "/work/project-visual",
        [{"type": "input_text", "text": f"Escaped symlink: {assets['escaped']}"}],
    )


def visual_compacted_image(_assets: dict[str, Path]) -> list[dict]:
    records = [
        session_meta("visual-compacted-image", "/work/project-visual"),
        turn_context("/work/project-visual"),
        message("user", "context padding " + ("x" * 2_000)),
        event("turn_complete", "turn complete"),
    ]
    records.append(
        {
            "timestamp": TS,
            "type": "compacted",
            "payload": {
                "message": "summary with visual payload",
                "replacement_history": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_image",
                                "image_url": f"data:image/png;base64,{TINY_PNG_BASE64}",
                            }
                        ],
                    }
                ],
            },
        }
    )
    return records


def build() -> None:
    assets = write_visual_assets()
    fixtures = {
        "healthy.jsonl": healthy(),
        "compaction-success.jsonl": compaction_success(),
        "compaction-failed.jsonl": compaction_failed(),
        "many-compactions.jsonl": many_compactions(),
        "discussion-only.jsonl": discussion_only(),
        "token-cumulative-high.jsonl": token_cumulative_high(),
        "token-cumulative-older.jsonl": token_cumulative_older_same_project(),
        "token-multiple-events.jsonl": token_multiple_events(),
        "event-failure.jsonl": event_failure(),
        "event-aliases.jsonl": event_aliases(),
        "runtime-error.jsonl": runtime_error(),
        "visual-embedded-image.jsonl": visual_embedded_image(assets),
        "visual-local-images-event.jsonl": visual_local_images_event(assets),
        "visual-markdown-paths.jsonl": visual_markdown_paths(assets),
        "visual-video-reference.jsonl": visual_video_reference(assets),
        "visual-duplicates.jsonl": visual_duplicates(assets),
        "visual-malformed-and-missing.jsonl": visual_malformed_and_missing(assets),
        "visual-symlink-escape.jsonl": visual_symlink_escape(assets),
        "visual-compacted-image.jsonl": visual_compacted_image(assets),
    }
    for name, records in fixtures.items():
        write_jsonl(ROOT / name, records)


if __name__ == "__main__":
    build()
