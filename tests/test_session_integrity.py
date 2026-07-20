from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
import pytest

from codex_thread_tools.session_integrity import (
    INVALID_INLINE_IMAGE_CODE,
    REMOTE_IMAGE_CODE,
    SessionIntegrityFinding,
    SessionIntegrityScanResult,
    scan_session_integrity,
)


def write_session(path: Path, records: list[dict]) -> None:
    payload = "\n".join(json.dumps(record) for record in records)
    path.write_text(f"{payload}\n", encoding="utf-8")


def message_record(content: list[dict]) -> dict:
    return {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": content,
        },
    }


def test_canonical_data_image_is_clean(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,iVBORw0KGgo=",
                    }
                ]
            ),
        ],
    )

    result = scan_session_integrity(path)

    assert result == SessionIntegrityScanResult(
        invalid_image_urls=0,
        invalid_image_urls_in_compacted_records=0,
        remote_image_urls=0,
        remote_image_urls_in_compacted_records=0,
        history_base_present=False,
        findings=(),
    )


def test_data_url_variants_support_valid_unpadded_and_padded_payloads(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,TQ",
                    }
                ]
            ),
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,TWE",
                    }
                ]
            ),
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,TQ==",
                    }
                ]
            ),
        ],
    )

    result = scan_session_integrity(path)

    assert result.invalid_image_urls == 0
    assert result.remote_image_urls == 0
    assert result.findings == ()


def test_model_visible_input_image_url_variants_are_scanned_as_input(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "https://example.com/image-a.png",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "InputImage",
                            "image_url": "https://example.com/image-b.png",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "inputImage",
                            "imageUrl": "https://example.com/image-c.png",
                        }
                    ],
                },
            },
        ],
    )

    result = scan_session_integrity(path)

    assert result.remote_image_urls == 3
    assert result.remote_image_urls_in_compacted_records == 0
    assert result.invalid_image_urls == 0
    assert {item.kind for item in result.findings} == {"input_image"}


def test_output_image_is_not_scanned_unless_explicit_input_image(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            message_record(
                [
                    {
                        "type": "output_image",
                        "image_url": "https://example.com/ignored.png",
                    }
                ]
            )
        ],
    )

    result = scan_session_integrity(path)

    assert result.remote_image_urls == 0
    assert result.invalid_image_urls == 0
    assert result.findings == ()


def test_malformed_inline_image_url_is_detected_without_leaking_payload(tmp_path: Path) -> None:
    malformed = "data:image/png;base64,this-is-not-valid"
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": malformed,
                    }
                ]
            )
        ],
    )

    result = scan_session_integrity(path)

    assert result.invalid_image_urls == 1
    assert result.invalid_image_urls_in_compacted_records == 0
    assert result.history_base_present is False
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding == SessionIntegrityFinding(
        kind="input_image",
        line=1,
        compacted=False,
        code=INVALID_INLINE_IMAGE_CODE,
    )
    assert set(asdict(finding).keys()) == {"kind", "line", "compacted", "code"}
    assert malformed not in repr(finding)


def test_invalid_input_urls_are_classified_as_invalid(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "file:///tmp/example.png",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "plain-string",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "data:text/plain;base64,abcd",
                        }
                    ],
                },
            },
        ],
    )

    result = scan_session_integrity(path)

    assert result.invalid_image_urls == 4
    assert result.remote_image_urls == 0
    assert result.findings == (
        SessionIntegrityFinding(kind="input_image", line=1, compacted=False, code=INVALID_INLINE_IMAGE_CODE),
        SessionIntegrityFinding(kind="input_image", line=2, compacted=False, code=INVALID_INLINE_IMAGE_CODE),
        SessionIntegrityFinding(kind="input_image", line=3, compacted=False, code=INVALID_INLINE_IMAGE_CODE),
        SessionIntegrityFinding(kind="input_image", line=4, compacted=False, code=INVALID_INLINE_IMAGE_CODE),
    )


def test_base64_padding_and_group_validation_for_input_urls(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,a",
                    }
                ]
            ),
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,a=b=",
                    }
                ]
            ),
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,TQ=",
                    }
                ]
            ),
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,TWE==",
                    }
                ]
            ),
        ],
    )

    result = scan_session_integrity(path)

    assert result.invalid_image_urls == 4
    assert result.findings == (
        SessionIntegrityFinding(
            kind="input_image",
            line=1,
            compacted=False,
            code=INVALID_INLINE_IMAGE_CODE,
        ),
        SessionIntegrityFinding(
            kind="input_image",
            line=2,
            compacted=False,
            code=INVALID_INLINE_IMAGE_CODE,
        ),
        SessionIntegrityFinding(
            kind="input_image",
            line=3,
            compacted=False,
            code=INVALID_INLINE_IMAGE_CODE,
        ),
        SessionIntegrityFinding(
            kind="input_image",
            line=4,
            compacted=False,
            code=INVALID_INLINE_IMAGE_CODE,
        ),
    )


def test_image_like_prose_and_tool_output_are_ignored_when_noncanonical(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            message_record(
                [
                    {
                        "type": "input_text",
                        "text": "This text includes data:image/png;base64,this-is-not-valid",
                    }
                ]
            ),
            {
                "type": "response_item",
                "payload": {
                    "type": "tool_output",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": {
                                "url": "data:image/png;base64,this-is-not-valid"
                            },
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": "not-canonical",
            },
        ],
    )

    result = scan_session_integrity(path)

    assert result.invalid_image_urls == 0
    assert result.remote_image_urls == 0
    assert result.findings == ()


def test_tool_call_output_image_with_invalid_non_data_url_is_reported_as_tool_output_image(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "output": [
                        {
                            "type": "input_image",
                            "image_url": "not-a-data-url",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": [
                        {
                            "type": "input_image",
                            "image_url": "",
                        }
                    ],
                },
            },
        ],
    )

    result = scan_session_integrity(path)

    assert result.invalid_image_urls == 2
    assert result.invalid_image_urls_in_compacted_records == 0
    assert result.remote_image_urls == 0
    assert result.remote_image_urls_in_compacted_records == 0
    assert result.findings == (
        SessionIntegrityFinding(
            kind="tool_output_image",
            line=1,
            compacted=False,
            code=INVALID_INLINE_IMAGE_CODE,
        ),
        SessionIntegrityFinding(
            kind="tool_output_image",
            line=2,
            compacted=False,
            code=INVALID_INLINE_IMAGE_CODE,
        ),
    )
    for finding in result.findings:
        assert set(asdict(finding).keys()) == {"kind", "line", "compacted", "code"}


@pytest.mark.parametrize(
    ("payload_type", "image_item", "expected_code"),
    [
        (
            "custom_tool_call_output",
            {"type": "input_image", "image_url": "not-a-data-url"},
            INVALID_INLINE_IMAGE_CODE,
        ),
        (
            "function_call_output",
            {"type": "InputImage", "image_url": ""},
            INVALID_INLINE_IMAGE_CODE,
        ),
        (
            "custom_tool_call_output",
            {"type": "inputImage", "imageUrl": "https://example.com/image.png"},
            REMOTE_IMAGE_CODE,
        ),
    ],
)
def test_compacted_tool_call_output_images_are_scanned_as_replayable_input(
    tmp_path: Path,
    payload_type: str,
    image_item: dict[str, str],
    expected_code: str,
) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            {
                "type": "compacted",
                "payload": {
                    "replacement_history": [
                        {
                            "type": payload_type,
                            "output": [image_item],
                        }
                    ]
                },
            }
        ],
    )

    result = scan_session_integrity(path)

    assert result.invalid_image_urls == int(expected_code == INVALID_INLINE_IMAGE_CODE)
    assert result.invalid_image_urls_in_compacted_records == int(
        expected_code == INVALID_INLINE_IMAGE_CODE
    )
    assert result.remote_image_urls == int(expected_code == REMOTE_IMAGE_CODE)
    assert result.remote_image_urls_in_compacted_records == int(
        expected_code == REMOTE_IMAGE_CODE
    )
    assert result.findings == (
        SessionIntegrityFinding(
            kind="tool_output_image",
            line=1,
            compacted=True,
            code=expected_code,
        ),
    )


def test_noncanonical_output_schema_with_input_image_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "tool_output",
                    "output": [
                        {
                            "type": "input_image",
                            "image_url": "not-a-data-url",
                        }
                    ],
                },
            }
        ],
    )

    result = scan_session_integrity(path)

    assert result.invalid_image_urls == 0
    assert result.remote_image_urls == 0
    assert result.findings == ()


def test_event_msg_with_message_payload_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            {
                "type": "event_msg",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "https://example.com/should-not-be-counted.png",
                        },
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,this-is-not-valid",
                        },
                    ],
                },
            },
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "https://example.com/should-be-counted.png",
                    }
                ]
            ),
        ],
    )

    result = scan_session_integrity(path)

    assert result.remote_image_urls == 1
    assert result.invalid_image_urls == 0
    assert len(result.findings) == 1
    assert result.findings[0] == SessionIntegrityFinding(
        kind="input_image",
        line=2,
        compacted=False,
        code=REMOTE_IMAGE_CODE,
    )


def test_malformed_compacted_image_uses_compacted_finding_context(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            {
                "type": "compacted",
                "payload": {
                    "message": "checkpoint",
                    "replacement_history": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_image",
                                    "image_url": "data:image/png;base64,this-is-not-valid",
                                },
                            ],
                        }
                    ],
                },
            }
        ],
    )

    result = scan_session_integrity(path)

    assert result.invalid_image_urls == 1
    assert result.invalid_image_urls_in_compacted_records == 1
    assert len(result.findings) == 1
    assert result.findings[0].compacted is True


def test_history_base_is_reported_as_metadata_without_resolution(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            {
                "type": "compacted",
                "history_base": "/tmp/history/12345.jsonl",
                "payload": {
                    "message": "checkpoint",
                    "replacement_history": [],
                },
            }
        ],
    )

    result = scan_session_integrity(path)

    assert result.history_base_present is True
    assert result.invalid_image_urls == 0
    assert result.invalid_image_urls_in_compacted_records == 0
    assert result.remote_image_urls == 0
    assert result.remote_image_urls_in_compacted_records == 0
    assert result.findings == ()


@pytest.mark.parametrize("max_findings", [True, 0.0, float("nan")])
def test_max_findings_must_be_strict_int(max_findings: object) -> None:
    with pytest.raises(ValueError, match="max_findings must be a non-negative integer"):
        scan_session_integrity(Path("/dev/null"), max_findings=max_findings)  # type: ignore[arg-type]


def test_findings_are_pointer_only_and_bounded_to_maximum(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session(
        path,
        [
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,this-is-not-valid",
                    }
                ]
            ),
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "https://example.com/1.png",
                    }
                ]
            ),
            message_record(
                [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,this-is-not-valid",
                    }
                ]
            ),
            {
                "type": "compacted",
                "payload": {
                    "message": "checkpoint",
                    "replacement_history": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "input_image",
                                    "image_url": "data:image/png;base64,this-is-not-valid",
                                }
                            ],
                        }
                    ],
                },
            },
        ],
    )

    result = scan_session_integrity(path, max_findings=2)

    assert result.invalid_image_urls == 3
    assert result.invalid_image_urls_in_compacted_records == 1
    assert result.remote_image_urls == 1
    assert result.remote_image_urls_in_compacted_records == 0
    assert len(result.findings) == 2
    for finding in result.findings:
        assert set(asdict(finding).keys()) == {"kind", "line", "compacted", "code"}
        assert isinstance(finding.line, int)
        assert finding.code in {INVALID_INLINE_IMAGE_CODE, REMOTE_IMAGE_CODE}
        assert finding.kind == "input_image"
    assert all(item.code != "" for item in result.findings)
