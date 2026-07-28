"""Browser-free guards for the unavailable-reading contract.

DEFERRED-BROWSER-01 (2026-07-26):
  The dashboards decide how an unavailable reading looks in CLIENT-SIDE
  JavaScript, so proving the rendered text requires a headless browser.
  tests/web/test_dashboard_unavailable_readings.py drives the real thing under
  Playwright, but Playwright is not a declared dependency of this project and is
  absent from CI, so that file cannot be the guard that protects the contract.

  These guards run everywhere and hold the two halves the browser test would
  otherwise be the only witness to:

    1. the API half, executed for real -- a non-finite Reading must cross the
       wire as strict-JSON ``null`` and never as ``NaN``/``Infinity``;
    2. the rendering half, checked from source -- every reading-value formatter
       in every bundled HTML/JS dashboard must sit in a comment-free conditional
       branch whose predicate checks that value's availability.

  The source check inventories ``toFixed``, ``toPrecision``, ``toExponential``,
  reading-value ``String``/``Number`` calls, ``Intl.NumberFormat(...).format``,
  and ``toLocaleString``. It recognizes direct reading values and local values
  produced by ``finiteNumber``; it does not prove alias-heavy JavaScript data
  flow or execute the browser. Executing the JS stays the browser test's job.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import cryodaq.web.server as server
from cryodaq.drivers.base import ChannelStatus, Reading

WEB_ROOT = Path("src/cryodaq/web")
SERVED_DASHBOARD = WEB_ROOT / "server.py"
_SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.DOTALL)
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_FORMATTING_CALL = re.compile(
    r"(?P<value>\b[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\.to"
    r"(?:Fixed|Precision|Exponential|LocaleString)\s*\(|"
    r"\b(?:String|Number)\s*\(\s*(?P<coerced>\b[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\.value\b)\s*\)|"
    r"\b(?:new\s+)?Intl\.NumberFormat\s*\([^)]*\)\.format\s*\(\s*"
    r"(?P<intl>\b[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\)"
)
_BOOLEAN_AVAILABILITY_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:isUsableReading\s*\(\s*(?P<reading>[A-Za-z_$][\w$]*)\s*\)|"
    r"Number\.isFinite\s*\(\s*(?P<number>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\))"
)
_NULLABLE_AVAILABILITY_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*finiteNumber\s*\([^)]*\)"
)
_DATE_VALUE_RE = re.compile(r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*new\s+Date\s*\(")
_CHANNEL_SPELLING_INFERENCE_RE = re.compile(
    r"\b(?:ch|channel|(?:msg|reading)\.channel)\s*\.\s*"
    r"(?:startsWith|endsWith|includes|match|search|indexOf)\s*\("
)


def _source(path: Path) -> str:
    """Read as bytes so CRLF files keep their endings and anchors still match."""
    return path.read_bytes().decode("utf-8")


def _dashboard_sources(root: Path = Path(".")) -> tuple[Path, ...]:
    """Return every bundled dashboard script source; an absent inventory is fatal."""

    web_root = root / WEB_ROOT
    served = root / SERVED_DASHBOARD
    sources = (served, *sorted(web_root.rglob("*.html")), *sorted(web_root.rglob("*.js")))
    assert sources and web_root.is_dir() and all(path.is_file() for path in sources), (
        "dashboard source inventory is missing or incomplete"
    )
    return sources


def _script_source(path: Path) -> str:
    source = _source(path)
    return source if path.suffix == ".js" else "\n".join(_SCRIPT_RE.findall(source))


def _availability_names(source: str) -> tuple[dict[str, str], set[str], set[str]]:
    code = _COMMENT_RE.sub("", source)
    return (
        {
            match.group("name"): match.group("reading") or match.group("number")
            for match in _BOOLEAN_AVAILABILITY_RE.finditer(code)
        },
        set(_NULLABLE_AVAILABILITY_RE.findall(code)),
        set(_DATE_VALUE_RE.findall(code)),
    )


def _formatter_value(match: re.Match[str]) -> str:
    return next(value for value in match.group("value", "coerced", "intl") if value is not None)


def _format_is_guarded(line: str, match: re.Match[str], booleans: dict[str, str], nullable: set[str]) -> bool:
    """Recognize a value-linked conditional branch, not a guard-shaped substring."""

    code = _COMMENT_RE.sub("", line)
    value = _formatter_value(match)
    prefix = code[: match.start()]
    question = prefix.rfind("?")
    if question < 0:
        return False
    condition_match = re.search(
        r"(?:isUsableReading\s*\([^)]*\)|Number\.isFinite\s*\([^)]*\)|"
        r"finiteNumber\s*\([^)]*\)\s*(?:===|!==)\s*null|"
        r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?\s*(?:===|!==)\s*null|"
        r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*$",
        prefix[:question],
    )
    if not condition_match:
        return False
    condition = condition_match.group(0).strip()
    in_false_branch = ":" in prefix[question + 1 :]
    if condition in booleans:
        return not in_false_branch and booleans[condition] in {value, value.rsplit(".", 1)[0]}
    if value in nullable:
        return (
            condition == f"{value} !== null"
            and not in_false_branch
            or (condition == f"{value} === null" and in_false_branch)
        )
    return (
        not in_false_branch
        and condition
        in {
            f"isUsableReading({value.rsplit('.', 1)[0]})",
            f"Number.isFinite({value})",
            f"finiteNumber({value}) !== null",
            f"{value} !== null",
        }
    ) or (in_false_branch and condition in {f"finiteNumber({value}) === null", f"{value} === null"})


def _unguarded_formatters(path: Path) -> list[str]:
    script = _script_source(path)
    booleans, nullable, dates = _availability_names(script)
    unguarded: list[str] = []
    for number, line in enumerate(script.splitlines(), 1):
        for match in _FORMATTING_CALL.finditer(line):
            if match.group("value") in dates and ".toLocaleString" in match.group(0):
                continue
            if not _format_is_guarded(line, match, booleans, nullable):
                unguarded.append(f"{path.as_posix()}:{number}: {line.strip()}")
    return unguarded


def test_dashboard_channels_are_not_classified_by_spelling() -> None:
    """A channel identifier may not select a measurement role by string shape."""

    findings = [
        f"{path.as_posix()}: {match.group(0)}"
        for path in _dashboard_sources()
        for match in _CHANNEL_SPELLING_INFERENCE_RE.finditer(_COMMENT_RE.sub("", _script_source(path)))
    ]
    assert not findings, "channel spelling inferred a dashboard role:\n" + "\n".join(findings)


@pytest.mark.parametrize("bad_shape", ("ch.startsWith('Т')", "msg.channel.match(/^T/)"))
def test_channel_spelling_guard_rejects_direct_inference_shapes(bad_shape: str) -> None:
    assert _CHANNEL_SPELLING_INFERENCE_RE.search(bad_shape)


def test_every_reading_formatter_has_a_structural_unavailability_branch() -> None:
    """Direct reading/finiteNumber formatters need a value-linked conditional branch."""

    unguarded = [site for path in _dashboard_sources() for site in _unguarded_formatters(path)]
    assert not unguarded, "numeric formatting without an unavailable guard:\n" + "\n".join(unguarded)


def test_both_dashboards_still_define_an_unavailable_helper() -> None:
    """The guards above are only meaningful while the helpers they name exist."""
    assert "function isUsableReading" in _source(SERVED_DASHBOARD)
    assert "function finiteNumber" in _source(WEB_ROOT / "static" / "index.html")


@pytest.mark.parametrize(
    "script, formatter",
    (
        ("const r={value:null}; const shown=String(r.value);", "String"),
        ("const r={value:null}; const shown=new Intl.NumberFormat().format(r.value);", "Intl.NumberFormat"),
        ("const r={value:null}; const shown=r.value.toLocaleString();", "toLocaleString"),
        ("const r={value:null}; /* usable */ const shown=r.value.toFixed(2);", "toFixed"),
        (
            "const r={value:null}, q={value:null}; const usable=isUsableReading(r); "
            "const shown=usable?String(q.value):'—';",
            "String",
        ),
    ),
)
def test_formatter_guard_rejects_unavailable_bypass_shapes(tmp_path: Path, script: str, formatter: str) -> None:
    dashboard = tmp_path / "dashboard.js"
    dashboard.write_text(script, encoding="utf-8")
    errors = _unguarded_formatters(dashboard)
    assert errors and formatter in errors[0]


def test_dashboard_inventory_fails_closed_when_the_web_tree_is_missing(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="inventory is missing"):
        _dashboard_sources(tmp_path)


def test_served_dashboard_distinguishes_unavailable_experiment_from_none() -> None:
    """The served dashboard must not render an unreachable engine as
    'Нет активного эксперимента'. The ``experiment_available`` signal must gate
    the experiment branch and must precede the no-experiment fallback, so an
    unavailable experiment status is rendered as a connectivity fault, not an
    authoritative empty. (The static dashboard consumes ``/status``, which
    carries no experiment field, so it is out of scope here.)"""
    src = _source(SERVED_DASHBOARD)
    assert "experiment_available" in src, "served dashboard lacks the experiment availability signal"
    availability = src.index("experiment_available")
    no_experiment = src.index("Нет активного эксперимента")
    assert availability < no_experiment, "availability check must precede the no-experiment fallback"


def test_served_dashboard_distinguishes_unavailable_log_from_empty() -> None:
    """The dashboard must render the log availability discriminator distinctly."""
    src = _source(SERVED_DASHBOARD)
    unavailable = src.index("ld.available===false")
    empty = src.index("ld.ok?'Нет записей'")
    assert unavailable < empty, "unavailable log check must precede the empty-log fallback"


@pytest.fixture
def unavailable_readings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Push non-finite readings through the production callback, not a stub."""

    async def _engine_reply(command: dict[str, object]) -> dict[str, object]:
        replies: dict[str, dict[str, object]] = {
            "safety_status": {"ok": True, "state": "safe"},
            "alarm_v2_status": {"ok": True, "active": {}},
            "experiment_status": {"ok": True},
            "log_get": {"ok": True, "entries": []},
        }
        return replies[str(command["cmd"])]

    monkeypatch.setattr(server, "_async_engine_command", _engine_reply)
    monkeypatch.setattr(server._state, "last_readings", {})
    monkeypatch.setattr(server._state, "active_alarms", {})
    for channel, value, unit in (
        ("T1", float("nan"), "K"),
        ("vacuum", float("inf"), "mbar"),
        ("keithley/smua/power", float("-inf"), "W"),
    ):
        server._on_reading_callback(
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="test",
                channel=channel,
                value=value,
                unit=unit,
                status=ChannelStatus.SENSOR_ERROR,
            )
        )


def test_api_reports_a_non_finite_reading_as_strict_json_null(unavailable_readings: None) -> None:
    """NaN and +/-inf must leave the server as null, which every JSON parser accepts."""
    app = server.create_app()

    @asynccontextmanager
    async def _no_background_workers(_app):
        """Serve the routes without connecting this regression to ZMQ."""
        yield

    app.router.lifespan_context = _no_background_workers
    with TestClient(app) as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    assert "NaN" not in response.text
    assert "Infinity" not in response.text
    readings = response.json()["readings"]
    assert readings["T1"]["value"] is None
    assert readings["vacuum"]["value"] is None
    assert readings["keithley/smua/power"]["value"] is None
