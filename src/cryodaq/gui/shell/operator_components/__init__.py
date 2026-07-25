"""Pure operator-snapshot presentation atoms.

The package renders immutable F36.1 summaries and emits navigation intent
only.  It deliberately owns no transport, routing, command, or safety logic.
"""

from .attention import AttentionList, AttentionRow
from .card import SnapshotCardShell
from .freshness import FreshnessProvenanceFooter
from .navigation import NavigationIntent, NextActionNavigationControl
from .readiness import ReadinessBlockerRow
from .status import CanonicalStatusLabel

__all__ = [
    "AttentionList",
    "AttentionRow",
    "CanonicalStatusLabel",
    "FreshnessProvenanceFooter",
    "NavigationIntent",
    "NextActionNavigationControl",
    "ReadinessBlockerRow",
    "SnapshotCardShell",
]
