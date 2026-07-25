"""F31 — sinks foundation.

Sinks fan out experiment-finalize events to external systems
(filesystem vault, HTTP webhooks). Fire-and-forget; failures are
captured in `SinkResult` rather than raised so the engine never blocks
on dispatch.
"""

from cryodaq.sinks.base import ExperimentExport, Sink, SinkResult
from cryodaq.sinks.registry import SinkRegistry
from cryodaq.sinks.vault_sink import VaultSink
from cryodaq.sinks.webhook_sink import WebhookSink

__all__ = [
    "ExperimentExport",
    "Sink",
    "SinkRegistry",
    "SinkResult",
    "VaultSink",
    "WebhookSink",
]
