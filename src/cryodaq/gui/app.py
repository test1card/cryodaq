"""Точка входа GUI-процесса CryoDAQ.

Запуск:
    cryodaq-gui             # через entry point
    python -m cryodaq.gui.app  # напрямую

Создаёт QApplication, запускает ZMQ bridge subprocess, открывает MainWindow.
GUI process не импортирует zmq — все ZMQ сокеты живут в subprocess.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable

import qdarktheme
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

# Theme module MUST be imported before any other cryodaq.gui submodule.
# It applies pyqtgraph global config at import time, which only takes
# effect for PlotWidget/GraphicsLayoutWidget instances created AFTER this
# import. See gui/theme.py docstring for the contract.
import cryodaq.gui.theme as theme  # noqa: F401 (side-effect import)
from cryodaq.gui.shell.main_window_v2 import MainWindowV2 as MainWindow
from cryodaq.gui.state.operator_snapshot_ingress import (
    OperatorSnapshotIngressOwner,
    start_operator_snapshot_ingress,
)
from cryodaq.gui.zmq_client import (
    ZmqBridge,
    open_gui_command_worker_admission,
    revoke_gui_command_worker_admission,
    set_bridge,
)
from cryodaq.instance_lock import release_lock_exact, try_acquire_lock
from cryodaq.operator_snapshot import SnapshotMode

logger = logging.getLogger("cryodaq.gui")


def _load_bundled_fonts() -> None:
    """Load bundled fonts (Fira Sans, Fira Code, Inter, JetBrains Mono).

    Must be called AFTER QApplication is created but BEFORE any widget
    that uses these fonts is constructed. Uses addApplicationFontFromData
    because addApplicationFont(path) fails on macOS PySide6/Qt6.
    """
    from pathlib import Path

    fonts_dir = Path(__file__).parent / "resources" / "fonts"
    if not fonts_dir.exists():
        logger.warning("Bundled fonts directory is unavailable")
        return

    font_files = [
        "Inter-Regular.ttf",
        "Inter-Medium.ttf",
        "Inter-SemiBold.ttf",
        "JetBrainsMono-Regular.ttf",
        "JetBrainsMono-Medium.ttf",
        "JetBrainsMono-SemiBold.ttf",
        "FiraCode-Regular.ttf",
        "FiraCode-Medium.ttf",
        "FiraCode-SemiBold.ttf",
        "FiraSans-Regular.ttf",
        "FiraSans-Medium.ttf",
        "FiraSans-SemiBold.ttf",
    ]

    loaded = 0
    for font_file in font_files:
        font_path = fonts_dir / font_file
        if not font_path.exists():
            logger.warning("Bundled font file is unavailable; font=%s", font_file)
            continue
        # B.5.7.2: use addApplicationFontFromData because
        # addApplicationFont(path) fails on macOS PySide6/Qt6
        from PySide6.QtCore import QByteArray

        data = font_path.read_bytes()
        font_id = QFontDatabase.addApplicationFontFromData(QByteArray(data))
        if font_id == -1:
            logger.warning(f"Failed to load font: {font_file}")
        else:
            loaded += 1
            families = QFontDatabase.applicationFontFamilies(font_id)
            logger.debug(f"Loaded {font_file}: families={families}")

    logger.info(f"Loaded {loaded}/{len(font_files)} bundled fonts")

    # Verify required families are now available (use theme tokens)
    all_families = QFontDatabase.families()
    for required in (theme.FONT_BODY, theme.FONT_DISPLAY):
        if required not in all_families:
            logger.warning(
                "Required font '%s' not found after registration. Design system will use system fallback.",
                required,
            )


def _enable_tabular_figures(font: QFont) -> None:
    """Enable OpenType tnum feature for stable digit widths.

    PySide6 6.11 exposes this via QFont.setFeature(QFont.Tag('tnum'), 1).
    Older / alternative APIs are tried as fallbacks. If none work, log a
    warning and continue — tabular figures are a quality-of-life feature,
    not a correctness requirement.
    """
    # PySide6 6.11+ Tag API
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
        return
    except (AttributeError, TypeError, ValueError):
        pass
    # PySide6 6.5–6.10 enum API (kept for forward/backward compat)
    try:
        font.setFeatures(QFont.Feature.TabularNumbers)  # type: ignore[attr-defined]
        return
    except (AttributeError, TypeError, ValueError):
        pass
    logger.warning("Tabular figures not supported by this PySide6 build")


def apply_fusion_dark_palette(app: QApplication) -> None:
    """Force Fusion style + design-token dark palette on the application.

    Must be called AFTER QApplication instantiation and BEFORE any
    widget is constructed. Idempotent — safe to call multiple times.

    Rationale. Linux systems with GTK-native Qt themes leak light
    defaults into widgets (QLineEdit / QSpinBox / QComboBox) and
    top-level window backgrounds, producing white strips inside our
    dark UI. Setting Fusion as the baseline style and pinning every
    palette role to a `theme.*` token makes the rendering deterministic
    across platforms.

    Composes with qdarktheme: call this AFTER `qdarktheme.setup_theme()`
    on the `cryodaq-gui` entry so our explicit palette wins, and call
    it standalone on entries that do not use qdarktheme (e.g. the
    `cryodaq` launcher). Existing application-level stylesheets (e.g.
    the sheet qdarktheme installs) are preserved — our menu/tooltip
    QSS is appended, not replaced.
    """
    app.setStyle("Fusion")
    # Qt6 wraps the active style in QStyleSheetStyle as soon as a
    # non-empty stylesheet is installed, which hides the underlying
    # Fusion identity from `app.style().objectName()` / metaObject.
    # Cache the fact that we set Fusion so tests and downstream code
    # can assert the invariant without unwrapping Qt internals.
    app.setProperty("_cryodaq_fusion_applied", True)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(theme.BACKGROUND))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.FOREGROUND))
    palette.setColor(QPalette.ColorRole.Base, QColor(theme.SURFACE_CARD))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.SURFACE_SUNKEN))
    palette.setColor(QPalette.ColorRole.Text, QColor(theme.FOREGROUND))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.MUTED_FOREGROUND))
    palette.setColor(QPalette.ColorRole.Button, QColor(theme.SURFACE_CARD))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.FOREGROUND))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.SURFACE_CARD))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.FOREGROUND))
    # Phase III.A/III.D Item 20: selected rows use the neutral
    # SELECTION_BG token, not ACCENT. Prior config set Highlight to
    # ACCENT which — for themes where ACCENT==STATUS_OK (warm_stone,
    # taupe_quiet pre-III.A) — rendered selected alarm rows green and
    # misled operators reading a CRIT row as "green = ok".
    palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.SELECTION_BG))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.FOREGROUND))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(theme.STATUS_FAULT))
    palette.setColor(QPalette.ColorRole.Link, QColor(theme.ACCENT))

    # Disabled state — muted foreground so inactive text stays legible
    # but clearly distinguishable from live text.
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(theme.MUTED_FOREGROUND),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(theme.MUTED_FOREGROUND),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(theme.MUTED_FOREGROUND),
    )

    app.setPalette(palette)

    # Minimal stylesheet for surfaces Fusion doesn't fully cover via
    # palette alone (tooltips keep a system border; QMenu selection
    # inherits platform defaults). Concatenate with any existing
    # app-level stylesheet so we don't wipe out contributions from
    # libraries that set their own (qdarktheme in particular).
    extras = (
        f"QToolTip {{"
        f"  background: {theme.SURFACE_CARD};"
        f"  color: {theme.FOREGROUND};"
        f"  border: 1px solid {theme.BORDER};"
        f"  padding: 4px;"
        f"}}"
        f"QMenu {{"
        f"  background: {theme.SURFACE_CARD};"
        f"  color: {theme.FOREGROUND};"
        f"  border: 1px solid {theme.BORDER};"
        f"}}"
        f"QMenu::item:selected {{"
        f"  background: {theme.ACCENT};"
        f"  color: {theme.ON_DESTRUCTIVE};"
        f"}}"
    )
    existing = app.styleSheet() or ""
    app.setStyleSheet((existing + "\n" + extras) if existing else extras)


class _GuiRuntimeOwners:
    """Retain every partially constructed GUI owner until exact settlement."""

    def __init__(self) -> None:
        self.bridge: ZmqBridge | None = None
        self.window: MainWindow | None = None
        self.snapshot_ingress: OperatorSnapshotIngressOwner | None = None
        self.timer: QTimer | None = None
        self.worker_session_epoch: int | None = None
        self._worker_session_revoked = False
        self._callbacks_open = True
        self._epoch = 1
        self._settled: set[str] = set()
        self._shutdown_retry_pending = False

    @property
    def epoch(self) -> int:
        return self._epoch

    def callback_is_current(self, epoch: int) -> bool:
        return self._callbacks_open and epoch == self._epoch

    def begin_shutdown(self) -> None:
        if self._callbacks_open:
            self._callbacks_open = False
            self._epoch += 1
        worker_session_epoch = self.worker_session_epoch
        if worker_session_epoch is not None and not self._worker_session_revoked:
            revoke_gui_command_worker_admission(worker_session_epoch)
            self._worker_session_revoked = True

    def request_shutdown(self, app: QApplication) -> None:
        """Accept one close request and keep retrying until every owner settles."""

        self.begin_shutdown()
        self._schedule_shutdown_retry(app, delay_ms=0)

    def _schedule_shutdown_retry(self, app: QApplication, *, delay_ms: int) -> None:
        if self._shutdown_retry_pending:
            return
        self._shutdown_retry_pending = True

        def retry() -> None:
            self._shutdown_retry_pending = False
            try:
                settled = self.settle()
            except Exception as exc:
                logger.error(
                    "GUI HOLD retry failed; exception=%s",
                    type(exc).__name__,
                )
                settled = False
            if settled:
                try:
                    app.quit()
                except Exception as exc:
                    logger.error(
                        "GUI application quit request failed; exception=%s",
                        type(exc).__name__,
                    )
                    self._schedule_shutdown_retry(app, delay_ms=1_000)
                return
            self._schedule_shutdown_retry(app, delay_ms=1_000)

        try:
            QTimer.singleShot(delay_ms, retry)
        except Exception:
            self._shutdown_retry_pending = False
            raise

    def settle(self) -> bool:
        self.begin_shutdown()
        errors: dict[str, Exception] = {}

        def attempt(label: str, action) -> None:  # noqa: ANN001
            if label in self._settled:
                return
            try:
                action()
            except Exception as exc:
                errors[label] = exc
            else:
                self._settled.add(label)

        timer = self.timer
        if timer is None:
            self._settled.add("timer")
        else:
            attempt("timer", lambda: timer.stop())

        window = self.window
        if window is None:
            self._settled.update({"window", "annunciation_terminal"})
        else:

            def settle_window() -> None:
                window.invalidate_descriptor_transport()
                if not window.settle_owned_workers():
                    raise RuntimeError("GUI descendant workers remain alive")

            attempt("window", settle_window)

        ingress = self.snapshot_ingress
        if ingress is None:
            self._settled.add("snapshot_ingress")
        else:

            def settle_ingress() -> None:
                ingress.stop()
                if ingress.active:
                    raise RuntimeError("snapshot ingress remained active")

            attempt("snapshot_ingress", settle_ingress)

        bridge = self.bridge
        if bridge is None:
            self._settled.update({"bridge_shutdown", "bridge_terminal", "bridge_registration"})
        elif {"window", "snapshot_ingress"}.issubset(self._settled):
            attempt("bridge_shutdown", lambda: bridge.shutdown())
            if "bridge_shutdown" in self._settled:
                attempt("bridge_terminal", lambda: bridge.close())
            if "bridge_terminal" in self._settled:

                def release_bridge() -> None:
                    set_bridge(None)
                    self.bridge = None

                attempt("bridge_registration", release_bridge)

        if window is not None and {
            "window",
            "snapshot_ingress",
            "bridge_shutdown",
            "bridge_terminal",
            "bridge_registration",
        }.issubset(self._settled):
            attempt("annunciation_terminal", window.complete_root_shutdown)

        for label, error in errors.items():
            logger.error(
                "GUI HOLD owner unsettled; owner=%s exception=%s",
                label,
                type(error).__name__,
            )
        required = {
            "timer",
            "window",
            "snapshot_ingress",
            "bridge_shutdown",
            "bridge_terminal",
            "bridge_registration",
            "annunciation_terminal",
        }
        return required.issubset(self._settled)


def _hold_gui_runtime(app: QApplication, owners: _GuiRuntimeOwners) -> None:
    """Drive owners to fail-closed settlement via the existing retry chain.

    This used to be an unbounded ``while True:`` that called
    ``owners.settle()`` directly from plain Python — outside any Qt event
    loop — and then pumped the event loop for a fixed second via a nested
    ``app.exec()`` before trying again. ``settle()`` walks down into
    ``MainWindow.settle_owned_workers()``, which an independent reviewer
    measured blocking the Qt main thread for 18.12s with 3 unresponsive
    workers; every second of that was also a second the annunciation
    alarm's QTimer could not fire, and the loop had no bound on how many
    times it could repeat that.

    ``settle_owned_workers()`` is now itself bounded to one small slice of
    wall clock per call (see ``_SETTLE_CALL_BUDGET_MS`` in
    ``shell/main_window_v2.py``), so a direct first check here is cheap.
    Anything left unsettled is handed to ``_GuiRuntimeOwners.request_shutdown``
    — the same QTimer-driven retry machinery ``MainWindow.closeEvent`` already
    uses via ``_root_shutdown_request`` — instead of a second, parallel
    retry loop. Running the real Qt event loop (one ``app.exec()``, not a
    repeated enter/exit) means the annunciation QTimer keeps firing on its
    own cadence for as long as HOLD lasts, instead of only in the gaps
    between hand-rolled pumping windows.

    HOLD stays fail-closed: this returns only once ``owners.settle()``
    reports every owner settled and the retry chain calls ``app.quit()``.
    It never gives up on an unsettled owner and never reports a clean exit
    early — there is still no retry-count ceiling, because abandoning an
    unsettled owner is exactly what the HOLD contract forbids.
    """

    try:
        if owners.settle():
            return
    except Exception as exc:
        logger.error(
            "GUI HOLD settlement attempt failed; exception=%s",
            type(exc).__name__,
        )
    owners.request_shutdown(app)
    app.exec()


def main() -> None:
    """Точка входа cryodaq-gui."""
    # NOTE: multiprocessing.freeze_support() is called in
    # cryodaq._frozen_main.main_gui() BEFORE importing this module.
    # Do not add it here — too late for Windows spawn bootloader because
    # PySide6 is already imported at module load time above.

    from cryodaq.logging_setup import resolve_log_level, setup_logging

    setup_logging("gui", level=resolve_log_level())

    app = QApplication(sys.argv)

    # Load bundled fonts BEFORE any widget is created
    _load_bundled_fonts()

    # Set default application font to Inter with tabular figures
    default_font = QFont(theme.FONT_UI, theme.FONT_BODY_SIZE)
    default_font.setWeight(QFont.Weight.Normal)
    _enable_tabular_figures(default_font)
    app.setFont(default_font)

    # Apply global dark theme. Must come after QApplication construction
    # and after fonts are loaded, before any window is shown.
    qdarktheme.setup_theme(
        theme="dark",
        corner_shape=theme.QDARKTHEME_CORNER_SHAPE,
        custom_colors={"primary": theme.QDARKTHEME_ACCENT},
    )

    # Force Fusion style + theme-token palette AFTER qdarktheme so our
    # explicit palette wins deterministically (fixes Linux GTK-native
    # theme leaks into QLineEdit / QSpinBox / QComboBox surfaces).
    apply_fusion_dark_palette(app)

    app.setApplicationName("CryoDAQ")
    app.setOrganizationName("АКЦ ФИАН")

    # Single-instance guard
    lock_fd = try_acquire_lock(".gui.lock")
    if lock_fd is None:
        QMessageBox.critical(
            None,
            "CryoDAQ",
            "CryoDAQ GUI уже запущен.\n\nИспользуйте уже открытый экземпляр.",
        )
        sys.exit(0)

    # --- ZMQ Bridge subprocess ---
    owners = _GuiRuntimeOwners()
    construction_phase = "gui_worker_session"
    try:
        owners.worker_session_epoch = open_gui_command_worker_admission()
        app.aboutToQuit.connect(owners.begin_shutdown)

        construction_phase = "bridge"
        bridge = ZmqBridge()
        owners.bridge = bridge
        set_bridge(bridge)
        bridge.start()

        construction_phase = "main_window"
        MainWindow(
            bridge=bridge,
            owner_anchor=lambda owner: setattr(owners, "window", owner),
            shutdown_request=lambda: owners.request_shutdown(app),
        )
        window = owners.window
        if window is None:
            raise RuntimeError("main window owner anchor was not invoked")

        construction_phase = "snapshot_ingress"
        start_operator_snapshot_ingress(
            bridge,
            window,
            expected_mode=SnapshotMode.LIVE,
            anchor=lambda owner: setattr(owners, "snapshot_ingress", owner),
        )
        snapshot_ingress = owners.snapshot_ingress
        if snapshot_ingress is None:
            raise RuntimeError("snapshot ingress owner anchor was not invoked")
        window.show()

        construction_phase = "poll_timer"
        timer = QTimer()
        owners.timer = timer
        timer.setInterval(10)
        callback_epoch = owners.epoch
        bridge_watchdog = _BridgeWatchdog()

        def _tick() -> None:
            if not owners.callback_is_current(callback_epoch):
                return
            _drain_bridge_readings(bridge, window)
            snapshot_ingress.pump()
            bridge_watchdog.tick(bridge=bridge, window=window, snapshot_ingress=snapshot_ingress)

        timer.timeout.connect(_tick)
        timer.start()
    except BaseException as exc:
        logger.critical(
            "GUI construction failed; phase=%s exception=%s",
            construction_phase,
            type(exc).__name__,
        )
        owners.begin_shutdown()
        _hold_gui_runtime(app, owners)
        release_lock_exact(lock_fd, ".gui.lock")
        raise SystemExit(1) from None

    logger.info("GUI запущен, ZMQ bridge subprocess active")

    # --- Qt event loop ---
    exit_code = app.exec()

    # --- Корректное завершение ---
    owners.begin_shutdown()
    _hold_gui_runtime(app, owners)
    release_lock_exact(lock_fd, ".gui.lock")
    logger.info("GUI завершён")

    sys.exit(exit_code)


def _drain_bridge_readings(bridge: ZmqBridge, window: MainWindow) -> None:
    """Drain one qualified batch through the production GUI ingress."""
    for qualified in bridge.poll_readings_with_descriptor():
        window.dispatch_qualified_reading(qualified)


# Latch repeated start exceptions, and pace non-raising restarts that have not
# yet restored engine health. The latter is deliberately a cooldown rather
# than a latch so a restarted engine can reconnect without restarting the GUI.
_BRIDGE_RESTART_ATTEMPT_LIMIT = 5
_BRIDGE_SUCCESSFUL_RESTART_COOLDOWN_S = 60.0


class _BridgeWatchdog:
    """Bound bridge restart resource churn without disabling recovery.

    A ``bridge.start()`` exception counts toward
    ``_BRIDGE_RESTART_ATTEMPT_LIMIT``; reaching the limit latches HOLD and
    :meth:`is_healthy` then fails closed. A non-raising ``start()`` only
    means its subprocess launched, not that the engine has connected. Such
    restarts are therefore retried no more often than
    ``_BRIDGE_SUCCESSFUL_RESTART_COOLDOWN_S`` by a monotonic clock. The
    cooldown bounds spawn-and-rollback churn while allowing an engine that
    comes back later to reconnect automatically.
    """

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._consecutive_failures = 0
        self._monotonic = monotonic
        self._next_restart_at: float | None = None
        self.latched = False

    def is_healthy(self, bridge: ZmqBridge) -> bool:
        """Fail-closed health probe: a latched bridge never reads healthy."""
        if self.latched:
            return False
        return bool(bridge.is_healthy())

    def tick(
        self,
        *,
        bridge: ZmqBridge,
        window: MainWindow,
        snapshot_ingress: OperatorSnapshotIngressOwner,
    ) -> None:
        """Restart the bridge subprocess when it stops reporting healthy."""
        if self.latched:
            return
        if not self.is_healthy(bridge):
            if not self._restart_is_due():
                return
            if bridge.is_alive():
                logger.warning("ZMQ bridge not healthy (no heartbeat), restarting...")
                self._restart(
                    bridge,
                    window,
                    snapshot_ingress,
                    shutdown_first=True,
                )
            else:
                logger.warning("ZMQ bridge died, restarting...")
                self._restart(
                    bridge,
                    window,
                    snapshot_ingress,
                    shutdown_first=False,
                )
            return
        if bridge.data_flow_stalled():
            if not self._restart_is_due():
                return
            logger.warning("ZMQ bridge not healthy (no readings), restarting...")
            self._restart(
                bridge,
                window,
                snapshot_ingress,
                shutdown_first=True,
            )

    def _restart_is_due(self) -> bool:
        """Return whether a health-driven restart may allocate a new bridge."""
        return self._next_restart_at is None or self._monotonic() >= self._next_restart_at

    def _restart(
        self,
        bridge: ZmqBridge,
        window: MainWindow,
        snapshot_ingress: OperatorSnapshotIngressOwner,
        *,
        shutdown_first: bool,
    ) -> None:
        """Invalidate all authority before one bridge replacement attempt."""
        failures: list[Exception] = []
        for invalidate in (
            snapshot_ingress.invalidate_transport,
            window.invalidate_descriptor_transport,
        ):
            try:
                invalidate()
            except Exception as exc:
                failures.append(exc)

        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise ExceptionGroup(
                "multiple standalone GUI authority invalidations failed",
                failures,
            )

        start_attempted = False
        try:
            if shutdown_first:
                bridge.shutdown()
            elif bridge.is_alive():
                # The caller observed a dead bridge.  If it came back in the
                # meantime, settle it before replacing it.
                bridge.shutdown()
            start_attempted = True
            bridge.start()
        except Exception as exc:
            if not start_attempted:
                raise
            self._consecutive_failures += 1
            if self._consecutive_failures >= _BRIDGE_RESTART_ATTEMPT_LIMIT:
                self.latched = True
                logger.critical(
                    "ZMQ bridge watchdog HOLD: %d consecutive restart failures "
                    "(limit=%d); giving up automatic recovery; failure=%s",
                    self._consecutive_failures,
                    _BRIDGE_RESTART_ATTEMPT_LIMIT,
                    type(exc).__name__,
                )
            else:
                logger.warning(
                    "ZMQ bridge restart failed (attempt %d/%d); exception=%s",
                    self._consecutive_failures,
                    _BRIDGE_RESTART_ATTEMPT_LIMIT,
                    type(exc).__name__,
                )
            return
        self._consecutive_failures = 0
        self._next_restart_at = self._monotonic() + _BRIDGE_SUCCESSFUL_RESTART_COOLDOWN_S


if __name__ == "__main__":
    main()
