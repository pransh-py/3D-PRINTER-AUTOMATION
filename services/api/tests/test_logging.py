"""Structured logging tests."""

import json
import logging

from xxx_api.logging import JsonFormatter


def test_json_formatter_includes_operational_context() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="xxx_api.request",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.event = "request.completed"
    record.request_id = "request-1"
    record.status_code = 200

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["event"] == "request.completed"
    assert payload["request_id"] == "request-1"
    assert payload["status_code"] == 200
