"""Offscreen-Qt smoke tests for the cooldown-baseline GUI (Task 8b).

Covers the «История охлаждений» card in the Архив overlay and the live
verdict badge in the Аналитика view. Mirrors ``tests/gui`` conventions:
QT_QPA_PLATFORM=offscreen, shared QApplication, no engine round-trip
(the feature reads a plain fingerprint directory on disk).
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.analytics.cooldown_fingerprint import (
    BASELINE_POINTER,
    CooldownFingerprint,
    get_baseline,
    save_fingerprint,
    set_baseline,
)
from cryodaq.gui.shell.overlays.cooldown_baseline_card import (
    CooldownBaselineCard,
    CooldownVerdictBadge,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _fp(
    fid: str,
    *,
    ts: float,
    duration_h: float = 12.0,
    T_cold_final: float = 4.2,
    time_to_base_h: float | None = 10.0,
    ultimate_vacuum_mbar: float | None = None,
) -> CooldownFingerprint:
    return CooldownFingerprint(
        fingerprint_id=fid,
        cooldown_start_ts=ts,
        duration_h=duration_h,
        T_cold_final=T_cold_final,
        time_to_base_h=time_to_base_h,
        time_to_50K_h=2.0,
        ultimate_vacuum_mbar=ultimate_vacuum_mbar,
        n_points=100,
    )


def _seed(history_dir: Path) -> None:
    save_fingerprint(_fp("cd_1000", ts=1000.0, time_to_base_h=10.0), history_dir)
    # Latest is markedly worse (>+30% time-to-base) → degraded vs baseline.
    save_fingerprint(_fp("cd_2000", ts=2000.0, time_to_base_h=20.0), history_dir)


# --------------------------------------------------------------------------
# Card
# --------------------------------------------------------------------------


def test_card_empty_state_when_disabled(tmp_path: Path) -> None:
    _app()
    _seed(tmp_path)
    card = CooldownBaselineCard(history_dir=tmp_path, enabled=False)
    assert card._empty_label.isVisibleTo(card)
    assert not card._table.isVisibleTo(card)
    assert card._table.rowCount() == 0


def test_card_empty_state_when_history_empty(tmp_path: Path) -> None:
    _app()
    card = CooldownBaselineCard(history_dir=tmp_path, enabled=True)
    assert card._empty_label.isVisibleTo(card)
    assert card._table.rowCount() == 0


def test_card_populates_from_history(tmp_path: Path) -> None:
    _app()
    _seed(tmp_path)
    card = CooldownBaselineCard(history_dir=tmp_path, enabled=True)
    assert card._table.rowCount() == 2
    assert not card._empty_label.isVisible()
    ids = {fp.fingerprint_id for fp in card.entries()}
    assert ids == {"cd_1000", "cd_2000"}


def test_pin_selected_writes_baseline_pointer(tmp_path: Path) -> None:
    _app()
    _seed(tmp_path)
    card = CooldownBaselineCard(history_dir=tmp_path, enabled=True)
    card.select_fingerprint("cd_1000")
    card._on_pin_clicked()
    assert (tmp_path / BASELINE_POINTER).exists()
    base = get_baseline(tmp_path)
    assert base is not None and base.fingerprint_id == "cd_1000"


def test_delta_display_vs_baseline(tmp_path: Path) -> None:
    _app()
    _seed(tmp_path)
    set_baseline("cd_1000", tmp_path)
    card = CooldownBaselineCard(history_dir=tmp_path, enabled=True)
    card.select_fingerprint("cd_2000")
    text = card._delta_label.text()
    # +10 h vs the 10 h baseline = +100% time-to-base — delta must be shown.
    assert "10" in text
    assert text != "—"


# --------------------------------------------------------------------------
# Badge
# --------------------------------------------------------------------------


def test_badge_hidden_when_disabled(tmp_path: Path) -> None:
    _app()
    _seed(tmp_path)
    set_baseline("cd_1000", tmp_path)
    badge = CooldownVerdictBadge(history_dir=tmp_path, enabled=False)
    assert not badge.isVisibleTo(None) or badge.verdict() is None
    assert badge.verdict() is None


def test_badge_hidden_without_baseline(tmp_path: Path) -> None:
    _app()
    _seed(tmp_path)
    badge = CooldownVerdictBadge(history_dir=tmp_path, enabled=True)
    assert badge.verdict() is None


def test_badge_reflects_degraded_verdict(tmp_path: Path) -> None:
    _app()
    _seed(tmp_path)
    set_baseline("cd_1000", tmp_path)
    badge = CooldownVerdictBadge(history_dir=tmp_path, enabled=True)
    assert badge.verdict() == "degraded"
    assert badge.text() != ""


def test_badge_reflects_ok_verdict(tmp_path: Path) -> None:
    _app()
    save_fingerprint(_fp("cd_1000", ts=1000.0, time_to_base_h=10.0), tmp_path)
    save_fingerprint(_fp("cd_2000", ts=2000.0, time_to_base_h=10.5), tmp_path)
    set_baseline("cd_1000", tmp_path)
    badge = CooldownVerdictBadge(history_dir=tmp_path, enabled=True)
    assert badge.verdict() == "ok"
