from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_notifier() -> ModuleType:
    script_path = Path(__file__).parents[1] / "scripts" / "coinjoin_notifier.py"
    spec = importlib.util.spec_from_file_location("coinjoin_notifier", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_notification_uses_neutral_amount() -> None:
    notifier = _load_notifier()

    _title, message, _priority = notifier.create_notification_message(
        {
            "role": "send",
            "success": "True",
            "confirmations": "0",
            "amount": "666",
            "cj_amount": "0",
        }
    )

    assert "(666 sats)" in message


def test_notification_falls_back_to_legacy_cj_amount() -> None:
    notifier = _load_notifier()

    _title, message, _priority = notifier.create_notification_message(
        {
            "role": "maker",
            "success": "True",
            "confirmations": "1",
            "cj_amount": "777",
        }
    )

    assert "(777 sats)" in message
