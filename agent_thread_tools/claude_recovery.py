"""Claude Code session checks and repairs used by ``recover``.

Claude Code sends ``message.content`` to the model when a session resumes. A
broken image there makes every later request fail, so ``strip_images`` rewrites
only those content blocks and leaves every other line byte-for-byte unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from agent_thread_tools.session_integrity import _is_valid_data_image_url
from agent_thread_tools.sessionlib import iter_jsonl

IMAGE_NOTE = "[image removed by agent-thread-tools recover strip-images]"


def inspect_claude(path: Path, *, largest_lines: int = 8) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "file": str(path),
        "agent": "claude",
        "bytes": path.stat().st_size,
        "total_records": 0,
        "record_types": {},
        "compact_boundaries": 0,
        "compact_summaries": 0,
        "sidechain_records": 0,
        "tool_uses": 0,
        "tool_results": 0,
        "images": 0,
        "image_bytes": 0,
        "api_errors": 0,
        "first_timestamp": "",
        "last_timestamp": "",
        "largest_lines": [],
    }
    largest: list[dict[str, Any]] = []
    for line_no, raw, record in iter_jsonl(path):
        summary["total_records"] += 1
        rtype = str(record.get("type", ""))
        summary["record_types"][rtype] = summary["record_types"].get(rtype, 0) + 1
        ts = record.get("timestamp") if isinstance(record.get("timestamp"), str) else ""
        if ts and not summary["first_timestamp"]:
            summary["first_timestamp"] = ts
        if ts:
            summary["last_timestamp"] = ts
        if record.get("subtype") == "compact_boundary":
            summary["compact_boundaries"] += 1
        if record.get("isCompactSummary"):
            summary["compact_summaries"] += 1
        if record.get("isSidechain"):
            summary["sidechain_records"] += 1
        if record.get("isApiErrorMessage"):
            summary["api_errors"] += 1
        for block in _content_blocks(record):
            btype = block.get("type")
            if btype == "tool_use":
                summary["tool_uses"] += 1
            elif btype == "tool_result":
                summary["tool_results"] += 1
            elif btype == "image":
                summary["images"] += 1
                data = _image_data(block)
                summary["image_bytes"] += len(data) * 3 // 4 if data else 0
        largest.append(
            {
                "line": line_no,
                "bytes": len(raw),
                "type": rtype,
                "subtype": record.get("subtype", ""),
                "timestamp": ts,
            }
        )
        largest.sort(key=lambda item: item["bytes"], reverse=True)
        del largest[largest_lines:]
    summary["largest_lines"] = largest
    return summary


def claude_findings(path: Path) -> dict[str, int]:
    """Problems that stop a Claude Code session from resuming cleanly."""
    tool_use_lines: dict[str, int] = {}
    answered: set[str] = set()
    last_user_line = 0
    image_api_errors = 0
    for line_no, _raw, record in iter_jsonl(path):
        if record.get("type") == "user":
            last_user_line = line_no
        if record.get("isApiErrorMessage") and "image" in _record_text(record).lower():
            image_api_errors += 1
        for block in _content_blocks(record, nested=False):
            if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                tool_use_lines.setdefault(block["id"], line_no)
            elif block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str):
                answered.add(block["tool_use_id"])
    # A call after the last user message may still be running; only earlier ones count.
    unanswered = sum(
        1
        for tool_id, line_no in tool_use_lines.items()
        if tool_id not in answered and line_no < last_user_line
    )
    return {"tool_calls_without_results": unanswered, "image_api_errors": image_api_errors}


def strip_images(source: Path, target: Path, *, all_images: bool) -> dict[str, int]:
    """Copy a session, replacing broken (or all) images with a short text note."""
    replaced = lines_changed = 0
    with target.open("wb") as handle:
        for _line_no, raw, record in iter_jsonl(source):
            count = _strip_record_images(record, all_images=all_images)
            if count:
                replaced += count
                lines_changed += 1
                handle.write(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    + b"\n"
                )
            else:
                handle.write(raw if raw.endswith(b"\n") else raw + b"\n")
    return {"images_replaced": replaced, "lines_changed": lines_changed}


def _strip_record_images(record: dict[str, Any], *, all_images: bool) -> int:
    message = record.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        return 0
    return _strip_blocks(message["content"], all_images=all_images)


def _strip_blocks(blocks: list[Any], *, all_images: bool) -> int:
    replaced = 0
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "image" and (all_images or not _image_is_valid(block)):
            blocks[index] = {"type": "text", "text": IMAGE_NOTE}
            replaced += 1
        elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
            replaced += _strip_blocks(block["content"], all_images=all_images)
    return replaced


def _image_is_valid(block: dict[str, Any]) -> bool:
    source = block.get("source")
    if not isinstance(source, dict):
        return False
    if source.get("type") == "url":
        return isinstance(source.get("url"), str)
    data = _image_data(block)
    media_type = source.get("media_type") or "image/png"
    return bool(data) and _is_valid_data_image_url(f"data:{media_type};base64,{data}")


def _image_data(block: dict[str, Any]) -> str:
    source = block.get("source")
    if isinstance(source, dict) and source.get("type") == "base64":
        data = source.get("data")
        return data if isinstance(data, str) else ""
    return ""


def _content_blocks(record: dict[str, Any], *, nested: bool = True) -> Iterator[dict[str, Any]]:
    message = record.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        return
    for block in message["content"]:
        if not isinstance(block, dict):
            continue
        yield block
        if nested and block.get("type") == "tool_result" and isinstance(block.get("content"), list):
            yield from (item for item in block["content"] if isinstance(item, dict))


def _record_text(record: dict[str, Any]) -> str:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return ""
