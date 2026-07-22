"""PyZMQ-free authority and receipt vocabulary for command transports.

The GUI process imports this module, so it must stay stdlib-only and must not
import :mod:`cryodaq.core.zmq_bridge`.  Unknown engine commands deliberately
default to ``MUTATION``: adding a dispatcher branch without updating the exact
read inventory cannot accidentally bypass compatibility negotiation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class CommandClass(Enum):
    """Trust class of one command action."""

    READ = "read"
    MUTATION = "mutation"
    SAFE_DIRECTION = "safe_direction"


MUTATION_PROTOCOL_MAJOR = 1
MUTATION_RECEIPT_SCHEMA = "mutation_compatibility_v1"
ENGINE_MUTATION_CAPABILITY = "cryodaq_mutation_v1"
REPLAY_MUTATION_CAPABILITY = "cryodaq_replay_mutation_v1"
MUTATION_ENVELOPE_KEYS = frozenset({"protocol_major", "mutation_capability", "capability_token"})

ASSISTANT_PROTOCOL_VERSION_ACTION = "assistant.protocol_version"
ASSISTANT_READ_ACTIONS = frozenset(
    {
        ASSISTANT_PROTOCOL_VERSION_ACTION,
        "assistant.query",
        "rag.search",
        "rag.rebuild_status",
    }
)
REPLAY_LOCAL_MUTATION_ACTIONS = frozenset({"experiment_create_retroactive", "experiment_advance_phase"})
SAFE_DIRECTION_ACTIONS = frozenset({"keithley_emergency_off"})

# Exact live-engine observational inventory.  ``assistant.*`` / ``rag.search``
# remain listed for the engine's legacy unavailable reply, even though current
# GUI routing sends them to the assistant REP.  All absent values fail closed.
ENGINE_READ_ACTIONS = frozenset(
    {
        "mutation_capabilities",
        "protocol_version",
        "periodic_subscription_barrier",
        "periodic_alarm_snapshot",
        "safety_status",
        "annunciation_status",
        "sinks_status",
        "alarm_v2_status",
        "recent_alarms",
        "alarm_v2_history",
        "get_app_mode",
        "experiment_templates",
        "experiment_status",
        "experiment_archive_list",
        "experiment_list_archive",
        "experiment_get_active",
        "experiment_get_archive_item",
        "experiment_phase_status",
        "calibration_acquisition_status",
        "calibration_v2_extract",
        "calibration_v2_coverage",
        "readings_history",
        "cooldown_history_get",
        "log_get",
        "calibration_curve_evaluate",
        "calibration_curve_list",
        "calibration_curve_get",
        "calibration_curve_lookup",
        "calibration_runtime_status",
        "get_sensor_diagnostics",
        "get_vacuum_trend",
        "cooldown_alarm.status",
        "vacuum_guard.status",
        "assistant.query",
        "rag.search",
        "multiline.burst_status",
        "rag.rebuild_status",
        "cooldown_eta_get",
    }
)
CLIENT_READ_ACTIONS = ENGINE_READ_ACTIONS | ASSISTANT_READ_ACTIONS


def classify_engine_command(action: object) -> CommandClass:
    """Classify a live-engine action, defaulting invalid/unknown to mutation."""

    if type(action) is str and action in ENGINE_READ_ACTIONS:
        return CommandClass.READ
    if type(action) is str and action in SAFE_DIRECTION_ACTIONS:
        return CommandClass.SAFE_DIRECTION
    return CommandClass.MUTATION


def classify_client_command(action: object) -> CommandClass:
    """Classify an action at GUI/web transport boundaries."""

    if type(action) is str and action in CLIENT_READ_ACTIONS:
        return CommandClass.READ
    if type(action) is str and action in SAFE_DIRECTION_ACTIONS:
        return CommandClass.SAFE_DIRECTION
    return CommandClass.MUTATION


def is_mutation(action: object) -> bool:
    """Return whether the live-engine action can change/publish state."""

    return classify_engine_command(action) is not CommandClass.READ


def requires_compatibility(action: object) -> bool:
    """Return whether an engine command needs an epoch compatibility receipt."""

    return classify_engine_command(action) is CommandClass.MUTATION


def requires_client_compatibility(action: object) -> bool:
    """Return whether a GUI/web command needs scoped compatibility discovery."""

    return classify_client_command(action) is CommandClass.MUTATION


def is_assistant_namespaced(action: object) -> bool:
    return type(action) is str and action.startswith(("assistant.", "rag."))


def valid_capability_token(token: object) -> bool:
    return type(token) is str and 16 <= len(token) <= 512 and token.isprintable()


def strip_mutation_envelope(command: dict[str, Any]) -> dict[str, Any]:
    """Copy a command without caller-supplied compatibility material."""

    return {key: value for key, value in command.items() if key not in MUTATION_ENVELOPE_KEYS}
