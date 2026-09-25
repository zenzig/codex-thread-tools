"""Translate Claude Code session JSONL records into the Codex record shape.

Claude Code stores each session as ``~/.claude/projects/<project>/<session>.jsonl``.
Its records are ``user``/``assistant``/``system`` messages plus bookkeeping
records. The analyzers in this package read Codex records (``session_meta``,
``response_item``, ``event_msg``, ``compacted``), so each Claude Code record is
translated into zero or more equivalent Codex records.
"""

from __future__ import annotations

import os
from typing import Any


DEFAULT_CONTEXT_WINDOW = 200_000
EXTENDED_CONTEXT_WINDOW = 1_000_000
INTERRUPT_PREFIX = "[Request interrupted by user"


def is_claude_record(record: dict[str, Any]) -> bool:
    return "payload" not in record and (
        "sessionId" in record or record.get("type") in {"user", "assistant", "system"}
    )


class ClaudeTranslator:
    """Stateful translator for one Claude Code session file."""

    def __init__(self) -> None:
        self.meta_emitted = False
        self.turn_open = False
        self.seen_message_ids: set[str] = set()
        self.cumulative: dict[str, int] = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
        self.context_window = _configured_context_window()

    def translate(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        ts = record.get("timestamp") if isinstance(record.get("timestamp"), str) else ""
        if not self.meta_emitted and isinstance(record.get("cwd"), str):
            self.meta_emitted = True
            out.append(
                {
                    "type": "session_meta",
                    "timestamp": ts,
                    "payload": {
                        "cwd": record["cwd"],
                        "id": record.get("sessionId", ""),
                        "originator": "claude-code",
                    },
                }
            )
        rtype = record.get("type")
        if rtype == "user":
            out.extend(self._user(record, ts))
        elif rtype == "assistant":
            out.extend(self._assistant(record, ts))
        elif rtype == "system":
            out.extend(self._system(record, ts))
        if not out:
            # Keep bookkeeping records visible to size and timestamp metrics.
            out.append({"type": f"claude_{rtype}", "timestamp": ts})
        return out

    def _user(self, record: dict[str, Any], ts: str) -> list[dict[str, Any]]:
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = _codex_content(message.get("content"), "input_text")
        text = "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
        if record.get("isCompactSummary"):
            return [
                {
                    "type": "compacted",
                    "timestamp": ts,
                    "payload": {"message": text, "replacement_history": content},
                }
            ]
        out: list[dict[str, Any]] = []
        is_tool_result = any(
            isinstance(item, dict) and item.get("type") == "function_call_output"
            for item in content
        )
        if text.startswith(INTERRUPT_PREFIX):
            if self.turn_open:
                self.turn_open = False
                out.append(_event(ts, "turn_aborted", text))
            return out
        if is_tool_result:
            out.append(
                {
                    "type": "response_item",
                    "timestamp": ts,
                    "payload": {"type": "function_call_output", "output": content},
                }
            )
            return out
        if record.get("isMeta"):
            return out
        if not self.turn_open:
            self.turn_open = True
            out.append(_event(ts, "task_started", ""))
        out.append(
            {
                "type": "response_item",
                "timestamp": ts,
                "payload": {"type": "message", "role": "user", "content": content},
            }
        )
        return out

    def _assistant(self, record: dict[str, Any], ts: str) -> list[dict[str, Any]]:
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = _codex_content(message.get("content"), "output_text")
        out: list[dict[str, Any]] = [
            {
                "type": "response_item",
                "timestamp": ts,
                "payload": {"type": "message", "role": "assistant", "content": content},
            }
        ]
        if message.get("stop_reason") == "end_turn" and self.turn_open:
            # Print-mode sessions never write turn_duration; end_turn closes the turn.
            self.turn_open = False
            out.append(_event(ts, "task_complete", ""))
        if record.get("isApiErrorMessage"):
            text = "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
            self.turn_open = False
            out.append(_event(ts, "error", text))
        usage = message.get("usage")
        message_id = message.get("id")
        if isinstance(usage, dict) and message.get("model") != "<synthetic>":
            token_event = self._token_event(usage, message_id, ts)
            if token_event:
                out.append(token_event)
        return out

    def _system(self, record: dict[str, Any], ts: str) -> list[dict[str, Any]]:
        subtype = record.get("subtype")
        if subtype == "turn_duration":
            if not self.turn_open:
                return []
            self.turn_open = False
            return [_event(ts, "task_complete", "")]
        if subtype == "compact_boundary":
            metadata = record.get("compactMetadata")
            if isinstance(metadata, dict):
                pre_tokens = metadata.get("preTokens")
                if isinstance(pre_tokens, int) and pre_tokens > self.context_window:
                    self.context_window = EXTENDED_CONTEXT_WINDOW
            return [_event(ts, "context_compacted", "")]
        return []

    def _token_event(
        self, usage: dict[str, Any], message_id: Any, ts: str
    ) -> dict[str, Any] | None:
        fresh = _int(usage.get("input_tokens")) + _int(usage.get("cache_creation_input_tokens"))
        cached = _int(usage.get("cache_read_input_tokens"))
        output = _int(usage.get("output_tokens"))
        active = fresh + cached + output
        if active == 0:
            return None
        if isinstance(message_id, str):
            if message_id in self.seen_message_ids:
                return None
            self.seen_message_ids.add(message_id)
        if active > self.context_window and _configured_context_window() == DEFAULT_CONTEXT_WINDOW:
            self.context_window = EXTENDED_CONTEXT_WINDOW
        self.cumulative["input_tokens"] += fresh + cached
        self.cumulative["cached_input_tokens"] += cached
        self.cumulative["output_tokens"] += output
        self.cumulative["total_tokens"] += active
        return {
            "type": "event_msg",
            "timestamp": ts,
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": dict(self.cumulative),
                    "last_token_usage": {
                        "input_tokens": fresh + cached,
                        "cached_input_tokens": cached,
                        "output_tokens": output,
                        "total_tokens": active,
                    },
                    "model_context_window": self.context_window,
                },
            },
        }


def _event(ts: str, event_type: str, message: str) -> dict[str, Any]:
    return {"type": "event_msg", "timestamp": ts, "payload": {"type": event_type, "message": message}}


def _codex_content(value: Any, text_type: str) -> list[dict[str, Any]]:
    """Convert Claude content (string or block list) into Codex content items."""
    if isinstance(value, str):
        return [{"type": text_type, "text": value}]
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for block in value:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text" and isinstance(block.get("text"), str):
            items.append({"type": text_type, "text": block["text"]})
        elif btype == "image":
            image = _image_item(block)
            if image:
                items.append(image)
        elif btype == "tool_result":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": block.get("tool_use_id", ""),
                    "output": _codex_content(block.get("content"), "input_text"),
                }
            )
        elif btype == "tool_use":
            items.append({"type": "function_call", "name": block.get("name", "")})
    return items


def _image_item(block: dict[str, Any]) -> dict[str, Any] | None:
    source = block.get("source")
    if not isinstance(source, dict):
        return None
    if source.get("type") == "base64":
        media_type = source.get("media_type") or "image/png"
        data = source.get("data")
        if isinstance(data, str):
            return {"type": "input_image", "image_url": f"data:{media_type};base64,{data}"}
    if source.get("type") == "url" and isinstance(source.get("url"), str):
        return {"type": "input_image", "image_url": source["url"]}
    return None


def _int(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _configured_context_window() -> int:
    raw = os.environ.get("CLAUDE_CONTEXT_WINDOW", "")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_CONTEXT_WINDOW
    return value if value > 0 else DEFAULT_CONTEXT_WINDOW
