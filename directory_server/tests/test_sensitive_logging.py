"""Tests for directory server sensitive logging."""

from __future__ import annotations

from io import StringIO

import pytest
from loguru import logger

from directory_server.main import setup_logging


@pytest.mark.parametrize("sensitive", [False, True])
def test_custom_stderr_sink_filters_sensitive_records(
    monkeypatch: pytest.MonkeyPatch, sensitive: bool
) -> None:
    output = StringIO()
    monkeypatch.setattr("directory_server.main.sys.stderr", output)
    setup_logging("INFO", sensitive=sensitive)

    logger.info("ordinary-directory-record")
    logger.bind(sensitive=True).info("private-directory-record")

    rendered = output.getvalue()
    assert "ordinary-directory-record" in rendered
    assert ("private-directory-record" in rendered) is sensitive
