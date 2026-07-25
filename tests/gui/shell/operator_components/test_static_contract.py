from __future__ import annotations

import re
from pathlib import Path


def test_operator_components_use_no_local_qss_or_raw_colors():
    root = Path("src/cryodaq/gui/shell/operator_components")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))

    assert "setStyleSheet" not in source
    assert "styleSheet()" not in source
    assert re.search(r"#[0-9a-fA-F]{6}", source) is None


def test_operator_components_import_no_transport_or_command_modules():
    root = Path("src/cryodaq/gui/shell/operator_components")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))

    for forbidden in ("import zmq", "zmq_client", "send_command", "rest_api", "SafetyManager"):
        assert forbidden not in source
