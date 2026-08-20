"""A colours file must never be the reason the program does not start.

WHY THIS MODULE EXISTS. ``cryodaq.gui.theme`` calls ``load_theme()`` at module level, so
whatever ``resolve_theme()`` does happens before the first window exists. It used to raise
``RuntimeError`` when the default pack could not be read -- missing, unparseable, short of
a token, or holding a value that is not a colour. On the laboratory machine that is a
program that will not start, during a run that is hours in and a cryostat that is cold,
because of a file that decides nothing but which greys to draw.

Owner, 2026-08-20: "файл цветов не должен останавливать".

The check is kept and the reason is recorded; only the stopping is gone. These tests drive
the real loader against a real, deliberately broken configuration directory.
"""

from __future__ import annotations

import logging
import pathlib

import pytest
import yaml

from cryodaq import logging_setup
from cryodaq.gui import _theme_loader


@pytest.fixture
def themes_dir(tmp_path, monkeypatch):
    """Point the loader at an empty configuration directory it fully owns."""

    directory = tmp_path / "themes"
    directory.mkdir()
    monkeypatch.setattr(_theme_loader, "THEMES_DIR", directory)
    monkeypatch.setattr(_theme_loader, "SETTINGS_FILE", tmp_path / "settings.local.yaml")
    return directory


def _write(directory, name: str, pack: dict) -> None:
    (directory / f"{name}.yaml").write_text(yaml.safe_dump(pack, allow_unicode=True), encoding="utf-8")


def _good_pack() -> dict:
    """A pack that passes validation, built from the in-code copy."""

    return _theme_loader.last_resort_pack()


# --------------------------------------------------------------------------- the defect


def test_a_missing_default_pack_does_not_stop_the_program(themes_dir, caplog) -> None:
    """Nothing at all in the themes directory. This used to raise."""

    with caplog.at_level(logging.CRITICAL, logger=_theme_loader.__name__):
        name, pack = _theme_loader.resolve_theme()

    assert name == _theme_loader.DEFAULT_THEME
    assert pack["BACKGROUND"] == "#1a1816"
    assert any("built-in copy" in record.getMessage() for record in caplog.records), (
        "the operator must be able to find out why, so the reason has to reach the log"
    )


@pytest.mark.parametrize(
    ("what", "content"),
    [
        ("unparseable", "BACKGROUND: '#1a1816'\n  bad indent: ["),
        ("not a mapping", "- just\n- a list\n"),
        ("empty", ""),
    ],
)
def test_a_damaged_default_pack_does_not_stop_the_program(themes_dir, what, content) -> None:
    """The ways a file actually breaks: a half-written copy, or the wrong shape."""

    (themes_dir / f"{_theme_loader.DEFAULT_THEME}.yaml").write_text(content, encoding="utf-8")

    name, pack = _theme_loader.resolve_theme()
    assert name == _theme_loader.DEFAULT_THEME, what
    assert pack["STATUS_FAULT"] == "#c44545", what


def test_a_default_pack_short_of_one_token_does_not_stop_the_program(themes_dir) -> None:
    """One removed line is the likeliest hand edit, and it used to be fatal."""

    pack = _good_pack()
    del pack["STATUS_STALE"]
    _write(themes_dir, _theme_loader.DEFAULT_THEME, pack)

    _name, resolved = _theme_loader.resolve_theme()
    assert resolved["STATUS_STALE"] == "#5a5d68"


def test_a_default_pack_with_a_value_that_is_not_a_colour_does_not_stop_the_program(themes_dir) -> None:
    pack = _good_pack()
    pack["ACCENT"] = "warm sand"
    _write(themes_dir, _theme_loader.DEFAULT_THEME, pack)

    _name, resolved = _theme_loader.resolve_theme()
    assert resolved["ACCENT"] == "#b89e7a"


def test_the_compatibility_loader_also_stops_stopping(themes_dir) -> None:
    """``_load_theme_pack`` had the same two raises and the same consequence."""

    assert _theme_loader._load_theme_pack(_theme_loader.DEFAULT_THEME)["BACKGROUND"] == "#1a1816"
    assert _theme_loader._load_theme_pack("gost")["BACKGROUND"] == "#1a1816"


# ------------------------------------------------- the ways a file refuses to be READ


def test_a_themes_directory_that_cannot_be_searched_does_not_stop_the_program(themes_dir, monkeypatch) -> None:
    """`Path.is_file()` RAISES on EACCES or EIO. That is not a ThemePackError.

    An access-control entry on the directory, or an unhealthy filesystem, made the stat
    itself raise `OSError`, which walked straight past the handler that catches a bad pack
    and ended the program during import -- exactly the unreadable-colours-file case this
    module exists to survive. It is normalised now.
    """

    real_is_file = pathlib.Path.is_file

    def _refuses(self):
        if self.name.endswith(".yaml"):
            raise PermissionError(13, "Permission denied")
        return real_is_file(self)

    monkeypatch.setattr(pathlib.Path, "is_file", _refuses)

    name, pack = _theme_loader.resolve_theme()
    assert name == _theme_loader.DEFAULT_THEME
    assert pack["BACKGROUND"] == "#1a1816"


def test_an_unreadable_settings_file_does_not_stop_the_program(themes_dir, monkeypatch) -> None:
    """Same class, one level up: the file that only chooses a theme."""

    def _refuses(self):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(pathlib.Path, "exists", _refuses)
    _write(themes_dir, _theme_loader.DEFAULT_THEME, _good_pack())

    name, _pack = _theme_loader.resolve_theme()
    assert name == _theme_loader.DEFAULT_THEME


@pytest.fixture
def root_logging_restored():
    """setup_logging replaces every root handler, so put them back afterwards."""

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    logging_setup._deferred_records.clear()
    try:
        yield
    finally:
        for handler in list(root.handlers):
            if handler not in handlers:
                try:
                    handler.close()
                except Exception:
                    pass
                root.removeHandler(handler)
        for handler in handlers:
            if handler not in root.handlers:
                root.addHandler(handler)
        root.setLevel(level)
        logging_setup._deferred_records.clear()


def test_the_reason_reaches_the_log_file_that_did_not_exist_yet(
    themes_dir, tmp_path, monkeypatch, root_logging_restored
) -> None:
    """The record happens before logging exists, so it must be replayed, not just emitted.

    `cryodaq.gui.theme` resolves the pack at module level and every entry point imports it
    BEFORE calling setup_logging -- `gui/app.py` imports the theme at line 27 and configures
    logging at line 431. A plain logger call in that window reaches no file handler, and
    under the frozen pythonw launcher reaches nothing at all.

    So this drives the WHOLE order production uses: resolve the pack first, configure
    logging second, then read the file off disk. Asserting on a direct call to the replay
    helper would stay green if setup_logging stopped calling it, which is the whole risk.
    """

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)

    _theme_loader.resolve_theme()  # empty themes directory: the fallback fires
    assert logging_setup._deferred_records, "the reason must be held for the log that does not exist yet"

    logging_setup.setup_logging("theme-fallback-probe", console=False, file=True)
    logging.shutdown()

    written = (log_dir / "theme-fallback-probe.log").read_text(encoding="utf-8")
    assert "built-in copy" in written, written
    assert not logging_setup._deferred_records, "a replayed record must not be emitted twice"


def test_the_deferred_list_cannot_grow_without_bound() -> None:
    """A list filled before logging exists is a leak nothing would ever notice."""

    logging_setup._deferred_records.clear()
    for index in range(logging_setup._MAX_DEFERRED_RECORDS + 25):
        logging_setup.defer_record(logging.ERROR, "record %d", index)
    assert len(logging_setup._deferred_records) == logging_setup._MAX_DEFERRED_RECORDS
    logging_setup._deferred_records.clear()


def test_the_theme_menu_survives_a_directory_it_cannot_read(themes_dir, monkeypatch) -> None:
    """Surviving the import is not surviving startup.

    ``resolve_theme`` coming back with the built-in pack only gets the program as far as
    its window. ``LauncherWindow.__init__`` then builds the settings menu, which calls
    ``available_themes``, and the same ``OSError`` aborted window construction one step
    later -- so the colours file still stopped the program, just further along.
    """

    real_exists = pathlib.Path.exists

    def _refuses(self):
        if self.name == "themes":
            raise PermissionError(13, "Permission denied")
        return real_exists(self)

    monkeypatch.setattr(pathlib.Path, "exists", _refuses)
    assert _theme_loader.available_themes() == [], "an unreadable directory means no choices, not a crash"


def test_a_directory_that_cannot_be_listed_also_survives(themes_dir, monkeypatch) -> None:
    """exists() can answer while the listing still refuses."""

    def _refuses(self, _pattern):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(pathlib.Path, "glob", _refuses)
    assert _theme_loader.available_themes() == []


def test_an_ignored_theme_choice_says_why(themes_dir, tmp_path, monkeypatch, root_logging_restored) -> None:
    """The one place that can explain it, because the fallback is never reached.

    When the settings file cannot be read but the default pack CAN, resolve_theme returns
    the default and ``_default_pack_or_last_resort`` never runs -- so without a record here
    the operator's configured theme is dropped and nothing anywhere says so.
    """

    _write(themes_dir, _theme_loader.DEFAULT_THEME, _good_pack())
    real_exists = pathlib.Path.exists

    def _refuses(self):
        if self.name == "settings.local.yaml":
            raise OSError(5, "Input/output error")
        return real_exists(self)

    monkeypatch.setattr(pathlib.Path, "exists", _refuses)

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)

    name, _pack = _theme_loader.resolve_theme()
    assert name == _theme_loader.DEFAULT_THEME
    assert logging_setup._deferred_records, "the reason must be held for the log that does not exist yet"

    monkeypatch.undo()  # restore Path.exists before logging touches the filesystem
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)
    logging_setup.setup_logging("theme-settings-probe", console=False, file=True)
    logging.shutdown()

    written = (log_dir / "theme-settings-probe.log").read_text(encoding="utf-8")
    assert "cannot read" in written, written


def test_every_reason_this_module_gives_survives_to_the_log() -> None:
    """One rule, checked once, instead of remembering it at eleven call sites.

    Three deferrals were missed by adding them one at a time: an unopenable settings file, a
    rejected pack, and an invalid pack in the inventory. They are all the same thing -- a
    reason produced during ``import cryodaq.gui.theme``, before any entry point has
    configured logging -- so they all go through one helper, and this fails if a bare logger
    call reappears.
    """

    source = pathlib.Path(_theme_loader.__file__).read_text(encoding="utf-8")
    bare = source.count("logger.warning(") + source.count("logger.error(") + source.count("logger.critical(")
    assert bare == 0, f"{bare} reason(s) would be lost before logging exists; use _say_and_defer"
    assert source.count("_say_and_defer(") >= 10


@pytest.mark.parametrize(
    ("what", "arrange"),
    [
        ("an unopenable settings file", "unopenable"),
        ("settings that are not a mapping", "not-a-mapping"),
        ("an invalid theme identifier", "bad-id"),
        ("a rejected chosen pack", "rejected"),
    ],
)
def test_each_dropped_choice_says_why(
    themes_dir, tmp_path, monkeypatch, root_logging_restored, what: str, arrange: str
) -> None:
    """Each way of ignoring the operator's choice must reach the log, not just the default.

    In every one of these the DEFAULT pack is readable, so the last-resort branch is never
    entered and these are the only places able to explain what happened.
    """

    _write(themes_dir, _theme_loader.DEFAULT_THEME, _good_pack())
    settings = tmp_path / "settings.local.yaml"

    if arrange == "unopenable":
        settings.write_text("theme: gost\n", encoding="utf-8")
        real_open = pathlib.Path.open

        def _refuses(self, *args, **kwargs):
            if self.name == "settings.local.yaml":
                raise PermissionError(13, "Permission denied")
            return real_open(self, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, "open", _refuses)
    elif arrange == "not-a-mapping":
        settings.write_text("- just\n- a list\n", encoding="utf-8")
    elif arrange == "bad-id":
        settings.write_text("theme: 'Not A Valid Id!'\n", encoding="utf-8")
    else:
        settings.write_text("theme: gost\n", encoding="utf-8")
        (themes_dir / "gost.yaml").write_text("not: [a, valid, pack", encoding="utf-8")

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)

    name, _pack = _theme_loader.resolve_theme()
    assert name == _theme_loader.DEFAULT_THEME, what
    assert logging_setup._deferred_records, f"{what}: nothing was held for the log"

    monkeypatch.undo()
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)
    logging_setup.setup_logging("theme-choice-probe", console=False, file=True)
    logging.shutdown()

    written = (log_dir / "theme-choice-probe.log").read_text(encoding="utf-8")
    assert "theme:" in written, f"{what}: {written!r}"


# ------------------------------------------------------------- a working pack still wins


def test_a_readable_pack_is_still_preferred_over_the_built_in_copy(themes_dir) -> None:
    """The fallback must not quietly take over from a pack that is perfectly fine."""

    pack = _good_pack()
    pack["BACKGROUND"] = "#010203"
    _write(themes_dir, _theme_loader.DEFAULT_THEME, pack)

    name, resolved = _theme_loader.resolve_theme()
    assert name == _theme_loader.DEFAULT_THEME
    assert resolved["BACKGROUND"] == "#010203", "the file on disk is still the authority when it is readable"


def test_a_broken_choice_still_falls_back_to_the_readable_default(themes_dir, tmp_path) -> None:
    """The pre-existing behaviour for a bad CHOICE is unchanged."""

    good = _good_pack()
    good["BACKGROUND"] = "#040506"
    _write(themes_dir, _theme_loader.DEFAULT_THEME, good)
    (themes_dir / "gost.yaml").write_text("not: [a, valid, pack", encoding="utf-8")
    (tmp_path / "settings.local.yaml").write_text("theme: gost\n", encoding="utf-8")

    name, resolved = _theme_loader.resolve_theme()
    assert name == _theme_loader.DEFAULT_THEME
    assert resolved["BACKGROUND"] == "#040506", "a broken choice falls back to the FILE, not to the built-in copy"


# ------------------------------------------------------------------ the copy cannot drift


def test_the_in_code_copy_matches_the_shipped_default_pack() -> None:
    """A frozen copy that nobody checks becomes a frozen copy that is wrong.

    Only the tokens and the display name are pinned. The description is deliberately
    different, because it has to tell the operator that these colours came from the
    program rather than from the file.
    """

    shipped = yaml.safe_load(
        (_theme_loader.THEMES_DIR / f"{_theme_loader.DEFAULT_THEME}.yaml").read_text(encoding="utf-8")
    )
    built_in = _theme_loader.last_resort_pack()

    for token in sorted(_theme_loader.REQUIRED_TOKENS):
        assert built_in[token] == shipped[token], f"{token} drifted from the shipped default pack"
    assert built_in["__meta_name__"] == shipped["__meta_name__"]
    assert built_in["__meta_description__"] != shipped["__meta_description__"], (
        "the description must say the colours came from the program, not repeat the file's own"
    )


def test_the_in_code_copy_would_pass_the_validator(themes_dir) -> None:
    """Whatever the loader hands back must satisfy the same contract a file does."""

    _write(themes_dir, "in_code_copy", _theme_loader.last_resort_pack())
    validated = _theme_loader.validate_theme_pack("in_code_copy")
    assert set(_theme_loader.REQUIRED_TOKENS) <= set(validated)


def test_the_built_in_copy_cannot_be_corrupted_by_a_caller() -> None:
    """It is handed out by copy, so one careless consumer cannot poison every later one."""

    first = _theme_loader.last_resort_pack()
    first["BACKGROUND"] = "#ffffff"
    assert _theme_loader.last_resort_pack()["BACKGROUND"] == "#1a1816"
