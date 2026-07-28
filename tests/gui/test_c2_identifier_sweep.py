"""Filesystem-only PARTIAL C2 seal.

This guard records every raw GUI identifier comparison it can mechanically
recognise.  BLOCKED-ON-SCHEMA rows remain visible here: physical landmarks,
analytics semantic channels, and source-channel labels need capabilities that
``ChannelDescriptorV1`` does not have.  They are deliberately not an implicit
allowlist.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "gui"
_IDENTIFIER_NAMES = frozenset(
    {
        "ch",
        "ch_id",
        "channel",
        "channel_id",
        "channel_raw",
        "instrument_id",
        "measurement",
        "short_id",
        "source_key",
    }
)
_IDENTIFIER_ATTRS = frozenset({"channel", "channel_id", "instrument_id", "source_key"})
_STRING_METHODS = frozenset({"startswith", "endswith"})


@dataclass(frozen=True, slots=True)
class Site:
    """One source expression which gives an identifier a semantic meaning."""

    path: str
    line: int
    form: str


def _literal_strings(node: ast.AST) -> bool:
    return any(isinstance(child, ast.Constant) and isinstance(child.value, str) for child in ast.walk(node))


def _identifier_name(name: str) -> bool:
    return name.lower() in _IDENTIFIER_NAMES


def _identifier_roster_name(name: str) -> bool:
    return name.upper() == name and any(token in name for token in ("CHANNEL", "INSTRUMENT", "SOURCE"))


class _IdentifierSweep(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.sites: set[Site] = set()
        self._tainted: set[str] = set()
        self._literal_bindings: set[str] = set()

    def _record(self, node: ast.AST, form: str) -> None:
        self.sites.add(Site(self.path, node.lineno, form))

    def _is_identifier(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self._tainted or _identifier_name(node.id)
        if isinstance(node, ast.Attribute):
            return node.attr in _IDENTIFIER_ATTRS or self._is_identifier(node.value)
        if isinstance(node, ast.Subscript):
            return self._is_identifier(node.value) or (
                isinstance(node.slice, ast.Constant) and node.slice.value in _IDENTIFIER_ATTRS
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            return self._is_identifier(node.func.value)
        if isinstance(node, ast.BinOp):
            return self._is_identifier(node.left) or self._is_identifier(node.right)
        if isinstance(node, ast.JoinedStr):
            return any(self._is_identifier(value) for value in node.values)
        return False

    def _bind(self, target: ast.AST, value: ast.AST) -> None:
        if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)):
            for child_target, child_value in zip(target.elts, value.elts, strict=False):
                self._bind(child_target, child_value)
            return
        if isinstance(target, ast.Name):
            if self._is_identifier(value):
                self._tainted.add(target.id)
            if _literal_strings(value):
                self._literal_bindings.add(target.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        previous = self._tainted.copy(), self._literal_bindings.copy()
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if _identifier_name(argument.arg):
                self._tainted.add(argument.arg)
        if node.args.vararg and _identifier_name(node.args.vararg.arg):
            self._tainted.add(node.args.vararg.arg)
        if node.args.kwarg and _identifier_name(node.args.kwarg.arg):
            self._tainted.add(node.args.kwarg.arg)
        self.generic_visit(node)
        self._tainted, self._literal_bindings = previous

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._bind(target, node.value)
            if isinstance(target, ast.Name) and _identifier_roster_name(target.id) and _literal_strings(node.value):
                self._record(node, "literal-roster")
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._bind(node.target, node.value)
            if (
                isinstance(node.target, ast.Name)
                and _identifier_roster_name(node.target.id)
                and _literal_strings(node.value)
            ):
                self._record(node, "literal-roster")
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        operands = (node.left, *node.comparators)
        has_identifier = any(self._is_identifier(operand) for operand in operands)
        has_literal = _literal_strings(node) or any(
            isinstance(operand, ast.Name) and operand.id in self._literal_bindings for operand in operands
        )
        if has_identifier and has_literal:
            self._record(node, "comparison")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in _STRING_METHODS and self._is_identifier(node.func.value):
                self._record(node, node.func.attr)
            if (
                isinstance(node.func.value, ast.Dict)
                and node.func.attr == "get"
                and node.args
                and self._is_identifier(node.args[0])
            ):
                self._record(node, "map-key")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.value, ast.Dict) and self._is_identifier(node.slice):
            self._record(node, "map-key")
        self.generic_visit(node)


def find_identifier_sites(root: Path = _ROOT) -> set[Site]:
    """Parse the working tree only; this intentionally never consults Git."""
    sites: set[Site] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _IdentifierSweep(path.relative_to(root).as_posix())
        visitor.visit(tree)
        sites.update(visitor.sites)
    return sites


def _rows(bucket: str, reason: str, *sites: Site) -> dict[Site, tuple[str, str]]:
    return {site: (bucket, reason) for site in sites}


# Each row is (bucket, reason), never a bare exception.  This is a PARTIAL C2
# seal: the blocked rows name the missing capability instead of hiding it.
REGISTRY: dict[Site, tuple[str, str]] = {}
REGISTRY.update(
    _rows(
        "LEGITIMATE",
        "Message/configuration correlation or display-only ordering; it does not assign a physical meaning.",
        Site("dashboard/dashboard_view.py", 264, "startswith"),
        Site("dashboard/dynamic_sensor_grid.py", 256, "comparison"),
        Site("dashboard/sensor_cell.py", 218, "startswith"),
        Site("first_run_config.py", 45, "literal-roster"),
        Site("first_run_config.py", 172, "literal-roster"),
        Site("first_run_config.py", 183, "literal-roster"),
        Site("first_run_config.py", 258, "comparison"),
        Site("first_run_config.py", 267, "comparison"),
        Site("first_run_config.py", 336, "startswith"),
        Site("first_run_config.py", 353, "startswith"),
        Site("first_run_config.py", 355, "comparison"),
        Site("first_run_config.py", 363, "comparison"),
        Site("first_run_config.py", 365, "startswith"),
        Site("first_run_config.py", 367, "comparison"),
        Site("first_run_wizard.py", 60, "literal-roster"),
        Site("shell/annunciation_controller.py", 35, "literal-roster"),
        Site("shell/annunciation_controller.py", 109, "comparison"),
        Site("shell/annunciation_controller.py", 274, "comparison"),
        Site("shell/annunciation_controller.py", 511, "comparison"),
        Site("shell/experiment_overlay.py", 580, "comparison"),
        Site("shell/main_window_v2.py", 737, "startswith"),
        Site("shell/main_window_v2.py", 753, "comparison"),
        Site("shell/main_window_v2.py", 758, "comparison"),
        Site("shell/main_window_v2.py", 769, "startswith"),
        Site("shell/main_window_v2.py", 781, "comparison"),
        Site("shell/main_window_v2.py", 904, "comparison"),
        Site("shell/main_window_v2.py", 963, "comparison"),
        Site("shell/overlays/calibration_panel.py", 62, "literal-roster"),
        Site("shell/overlays/calibration_panel.py", 112, "comparison"),
        Site("shell/overlays/operator_log_panel.py", 61, "literal-roster"),
        Site("shell/overlays/operator_log_panel.py", 1193, "comparison"),
        Site("shell/views/analytics_widgets.py", 1626, "startswith"),
        Site("shell/views/analytics_widgets.py", 1627, "comparison"),
        Site("shell/views/analytics_widgets.py", 1850, "comparison"),
    )
)
REGISTRY.update(
    _rows(
        "LEGITIMATE",
        "Positionally fixed T11/T12 landmark declared by config/cooldown.yaml and config/safety.yaml.",
        Site("dashboard/experiment_card.py", 46, "literal-roster"),
        Site("shell/top_watch_bar.py", 578, "literal-roster"),
        Site("shell/top_watch_bar.py", 579, "literal-roster"),
        Site("shell/top_watch_bar.py", 1092, "comparison"),
    )
)
REGISTRY.update(
    _rows(
        "BLOCKED-ON-SCHEMA",
        "Requires an analytics semantic-channel capability (ETA, R_thermal, vacuum, "
        "or health), absent from ChannelDescriptorV1.",
        Site("dashboard/phase_aware_widget.py", 371, "endswith"),
        Site("dashboard/phase_aware_widget.py", 374, "endswith"),
        Site("dashboard/phase_aware_widget.py", 377, "endswith"),
        Site("shell/main_window_v2.py", 1007, "comparison"),
        Site("shell/main_window_v2.py", 1011, "startswith"),
        Site("shell/main_window_v2.py", 1026, "comparison"),
        Site("shell/main_window_v2.py", 1029, "comparison"),
    )
)
REGISTRY.update(
    _rows(
        "BLOCKED-ON-SCHEMA",
        "Requires a source-channel label/list or temperature-chain membership "
        "capability; ChannelDescriptorV1 has neither.",
        Site("shell/main_window_v2.py", 761, "comparison"),
        Site("shell/overlays/conductivity_panel.py", 100, "literal-roster"),
        Site("shell/overlays/conductivity_panel.py", 109, "startswith"),
        Site("shell/overlays/conductivity_panel.py", 870, "comparison"),
        Site("shell/overlays/keithley_panel.py", 1180, "comparison"),
        Site("shell/overlays/keithley_panel.py", 1346, "startswith"),
        Site("shell/overlays/keithley_panel.py", 1356, "comparison"),
        Site("shell/overlays/keithley_panel.py", 1359, "endswith"),
        Site("shell/views/analytics_widgets.py", 736, "literal-roster"),
        Site("shell/views/analytics_widgets.py", 1268, "comparison"),
        Site("shell/views/analytics_widgets.py", 1269, "comparison"),
        Site("shell/views/analytics_widgets.py", 1274, "map-key"),
    )
)
REGISTRY.update(
    _rows(
        "BLOCKED-ON-SCHEMA",
        "Requires a MultiLine source-channel label/slot capability; generic quantity, "
        "role, safety, and presentation cannot identify the slot.",
        Site("shell/overlays/multiline_panel.py", 102, "comparison"),
        Site("shell/overlays/multiline_panel.py", 113, "comparison"),
        Site("shell/overlays/multiline_panel.py", 125, "comparison"),
        Site("shell/overlays/multiline_panel.py", 134, "comparison"),
        Site("shell/overlays/multiline_panel.py", 138, "comparison"),
        Site("shell/overlays/multiline_panel.py", 155, "comparison"),
        Site("shell/overlays/multiline_panel.py", 597, "startswith"),
        Site("shell/overlays/multiline_panel.py", 598, "comparison"),
    )
)


def assert_registered(root: Path = _ROOT) -> None:
    found = find_identifier_sites(root)
    missing = found - set(REGISTRY)
    stale = set(REGISTRY) - found
    assert not missing, "unregistered GUI identifier sites:\n" + "\n".join(
        f"{site.path}:{site.line} ({site.form})"
        for site in sorted(missing, key=lambda item: (item.path, item.line, item.form))
    )
    assert not stale, "registry rows no longer found:\n" + "\n".join(
        f"{site.path}:{site.line} ({site.form})"
        for site in sorted(stale, key=lambda item: (item.path, item.line, item.form))
    )
    assert {bucket for bucket, _ in REGISTRY.values()} <= {"LEGITIMATE", "BLOCKED-ON-SCHEMA"}
    assert all(reason for _, reason in REGISTRY.values())


def test_c2_identifier_population_is_registered() -> None:
    assert_registered()


def test_c2_identifier_guard_rejects_new_unregistered_site(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text("def route(channel):\n    return channel == 'new/unregistered/channel'\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="unregistered GUI identifier sites"):
        assert_registered(tmp_path)
