"""Identity shared by unqualified checkpoint artifact builders and gates."""

from __future__ import annotations

UNQUALIFIED_LABEL = "UNQUALIFIED — TEST ONLY"
UNQUALIFIED_LOCAL_VERSION = "checkpoint.unqualified"


def checkpoint_version(version: str) -> str:
    return f"{version.partition('+')[0]}+{UNQUALIFIED_LOCAL_VERSION}"
