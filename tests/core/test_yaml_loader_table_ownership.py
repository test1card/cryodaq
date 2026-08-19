"""The engine's YAML loaders must own their parsing tables.

Subclassing ``yaml.SafeLoader`` shares its mutable class attributes BY
REFERENCE.  Any library that calls ``yaml.SafeLoader.add_constructor(...)`` or
``add_implicit_resolver(...)`` -- documented public PyYAML APIs, ordinary use
rather than an attack -- then decides what these loaders parse.  Three engine
loaders were affected: the descriptor loader, the periodic-config loader, and
both legacy paths in the physical-alarms loader.

Two facts shape every test here, and both were paid for.

**Import ordering decides the outcome, so the interesting cases cannot run
in-process.**  By collection time ``cryodaq`` is long since imported, so an
in-process test can only exercise the easy ordering.  Every ordering assertion
below therefore runs in a fresh interpreter.

**``add_constructor`` is COPY-ON-WRITE.**  A loader that calls it gets a copy of
whatever the table held at that moment -- including a poisoned entry.  So a test
asserting ``Loader.yaml_constructors is not yaml.SafeLoader.yaml_constructors``
PASSES on the defective code and proves nothing.  The load-bearing assertions
here are behavioural: parse a document and look at the value that comes out.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# A library registers a resolver for bare scalars ending in K and a constructor
# that replaces them.  Nothing in it mentions cryodaq.
POISON = (
    "import re, yaml\n"
    'yaml.SafeLoader.add_implicit_resolver("!kelvin", re.compile(r"^\\d+(?:\\.\\d+)?K$"), list("0123456789"))\n'
    'yaml.SafeLoader.add_constructor("!kelvin", lambda loader, node: "POISONED")\n'
)

# The same shape, aimed at the canonical Cyrillic channel identities the SHIPPED
# production config actually carries.  Implicit resolvers key on the first
# character, which is U+0422 CYRILLIC CAPITAL TE -- not Latin T.
#
# *** AN IMPLICIT RESOLVER CANNOT REACH A QUOTED SCALAR. ***  This one therefore
# reaches the BARE landmark keys (`Т12:`) in physical_alarms.yaml and NOT the
# quoted safety-bearing fields (`cold_channel: "Т12"`).  Worse, it maps both
# landmark keys onto one value, so against the defective loader the duplicate-key
# refusal ABORTS startup -- which is a red result for the wrong reason.  Use
# CHANNEL_PATH_POISON below for anything asserting silent substitution of the
# channel identities themselves.
CHANNEL_POISON = (
    "import re as _re, yaml as _yaml\n"
    '_yaml.SafeLoader.add_implicit_resolver("!chan", _re.compile("^\\u0422[0-9]+$"), ["\\u0422"])\n'
    '_yaml.SafeLoader.add_constructor("!chan", lambda loader, node: "POISONED")\n'
)

# A PATH resolver retags by POSITION, so quoting is no defence.  It writes into
# `yaml_path_resolvers` -- the one shared table none of the other probes here
# exercise -- and it substitutes exactly the fields CooldownAlarm and VacuumGuard
# bind to, while leaving the landmark keys intact so no duplicate-key refusal can
# mask the result.  Measured on the shipped file: cold_channel, warm_channel and
# reference_temp_channel all become the substituted value; both landmarks survive.
CHANNEL_PATH_POISON = (
    "import yaml as _yaml\n"
    '_yaml.SafeLoader.add_path_resolver("!chan", ["cooldown", "cold_channel"], str)\n'
    '_yaml.SafeLoader.add_path_resolver("!chan", ["cooldown", "warm_channel"], str)\n'
    '_yaml.SafeLoader.add_path_resolver("!chan", ["vacuum", "reference_temp_channel"], str)\n'
    '_yaml.SafeLoader.add_constructor("!chan", lambda loader, node: "POISONED")\n'
)

SHIPPED_ALARMS_CONFIG = REPO_ROOT / "config" / "physical_alarms.yaml"
SHIPPED_ALARM_CONFIG = REPO_ROOT / "config" / "alarms_v3.yaml"

ALARMS_DOCUMENT = """\
cooldown:
  enabled: true
  eval_interval_s: 30
  k_p: 2.5
  sustained_min: 5
  base_temp_K: 5.0
  base_epsilon_K: 1.0
  eta_slip_window_min: 60
  eta_slip_message_threshold_h: 0.5
  auto_disarm_progress: 0.95
  cold_channel: 12K
  warm_channel: 11K
  predictor_model_path: data/cooldown_model/predictor_model.json
  auto_arm: true
  watchdog_enabled: false
  watchdog_margin_K: 1.0
  watchdog_sustained_s: 300.0
  watchdog_level: WARNING
  cold_start_skip_margin_K: 5.0
vacuum:
  enabled: true
  eval_interval_s: 30
  pressure_channel: VSP63D_1/pressure
  reference_temp_channel: 12K
  arm_threshold_K: 260.0
  disarm_threshold_K: 270.0
  fire_pressure_mbar: 1.0e-2
  clear_pressure_mbar: 1.0e-3
  sustained_s: 30
  severity: CRITICAL
  escalate_to_safety: false
landmarks:
  12K:
    role: cold_stage
    physical: 2-я ступень
    aliases: [холодная плита]
"""


def _run(source: str) -> str:
    """Execute ``source`` in a fresh interpreter against this working tree."""

    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "SystemRoot") if name in os.environ}
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", source],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _ordered(import_statement: str, body: str, *, order: str) -> str:
    """Assemble a probe where the library registers before or after the import."""

    assert order in {"pre", "post"}
    if order == "pre":
        return POISON + import_statement + body
    return import_statement + POISON + body


def _alarms_probe(document: Path, order: str) -> str:
    return _ordered(
        "from cryodaq.core.physical_alarms_config import load_channel_landmarks, load_physical_alarms_config\n",
        "import pathlib\n"
        f"path = pathlib.Path({str(document)!r})\n"
        "cooldown, vacuum = load_physical_alarms_config(path)\n"
        "landmarks = load_channel_landmarks(path)\n"
        'print("POISONED" if "POISONED" in repr((cooldown, vacuum, landmarks)) else "CLEAN")\n',
        order=order,
    )


def test_library_registration_after_import_cannot_reach_the_alarm_channel_identities(tmp_path: Path) -> None:
    """The realistic ordering: cryodaq imports first, the library registers later.

    Measured against the reverted production code, which called
    ``yaml.safe_load``: ``cold_channel``, ``warm_channel`` and
    ``reference_temp_channel`` all came back as the library's substituted
    string, and the loader returned that configuration *successfully*, with
    ``escalate_to_safety`` still false and no diagnostic.  The CooldownAlarm and
    VacuumGuard would have bound to channel identities that exist nowhere.
    """

    document = tmp_path / "physical_alarms.yaml"
    document.write_text(ALARMS_DOCUMENT, encoding="utf-8")
    assert _run(_alarms_probe(document, "post")) == "CLEAN"


def test_production_loader_snapshots_its_tables_at_import_not_at_call() -> None:
    """The PRODUCTION startup path, which the first version of this file missed.

    ``_UniqueSafeLoader`` was declared INSIDE
    ``load_production_physical_alarms_config``.  A class body executes when its
    statement executes, so the table copies were taken at CALL time -- from
    whatever ``yaml.SafeLoader`` held at engine startup, poisoned entry included.
    The earlier tests here all imported module-level loaders and so could not
    see it: they proved the property for three loaders and left the one on the
    startup path unexercised.

    This asserts the ordering that defect needed -- the library registers AFTER
    the module is imported but BEFORE the loader is called -- and it drives the
    SHIPPED ``config/physical_alarms.yaml`` rather than a fixture.

    *** THE POISON HERE WAS ONCE THE WRONG INSTRUMENT, AND ITS RED WAS A FRAMING
    ARTIFACT. ***  It used ``CHANNEL_POISON``, an implicit resolver, while the
    shipped file QUOTES ``cold_channel``, ``warm_channel`` and
    ``reference_temp_channel``.  Implicit resolvers do not apply to quoted
    scalars, so it never touched them -- it hit the bare landmark keys and mapped
    both onto one value, and the defective loader then went red on the
    DUPLICATE-KEY REFUSAL rather than on the silent substitution this test
    claims to demonstrate.  A guard that fails for the wrong reason still looks
    green when fixed.

    ``CHANNEL_PATH_POISON`` retags by POSITION, so quoting is no defence.

    **What each revert actually produces, measured against real production
    rather than assumed** -- the three cases are not equivalent and only one is
    the defect that shipped:

    ===========================================  ==========================
    arrangement                                  path-resolver poison gives
    ===========================================  ==========================
    class INSIDE the function (what shipped)     SILENT SUBSTITUTION of all
                                                 three channel identities,
                                                 landmarks intact, no
                                                 diagnostic
    module-level class on ``yaml.SafeLoader``    REFUSAL -- fail-closed
    module-level class on ``OwnedSafeLoader``    clean
    ===========================================  ==========================

    The middle row is why a red here must be read carefully: reverting only the
    BASE CLASS leaves ``add_constructor`` copy-on-writing the constructor table
    at IMPORT time, before any poison, so the retagged node finds no constructor
    and the loader raises.  That is red, and safe, and NOT the shipped defect.
    Only moving the class back inside the function reproduces the silent
    substitution this test exists to prevent.
    """

    probe = (
        "from cryodaq.core.physical_alarms_config import load_production_physical_alarms_config\n"
        + CHANNEL_PATH_POISON
        + "import pathlib\n"
        + f"path = pathlib.Path({str(SHIPPED_ALARMS_CONFIG)!r})\n"
        + "cooldown, vacuum, landmarks = load_production_physical_alarms_config(path)\n"
        # Assert the substitution target SPECIFICALLY, not just the absence of a
        # marker anywhere: the channel identities CooldownAlarm and VacuumGuard
        # bind to.  Checking only `"POISONED" not in repr(...)` would also pass
        # if the loader raised, or returned nothing at all.
        + "targets = (cooldown['cold_channel'], cooldown['warm_channel'], vacuum['reference_temp_channel'])\n"
        + "assert len(landmarks) == 2, f'landmarks collapsed to {sorted(landmarks)}: refusal may mask this'\n"
        + 'print("POISONED" if "POISONED" in targets else "CLEAN")\n'
    )
    assert _run(probe) == "CLEAN"


def test_shipped_alarm_config_channel_lists_cannot_be_substituted() -> None:
    """`core/alarm_config.py`, found in review after three loaders were fixed.

    It used bare ``yaml.safe_load`` and loads the CRITICAL alarm definitions.
    Measured before the fix, against the SHIPPED ``config/alarms_v3.yaml`` with a
    resolver registered AFTER the module imported: the ``vacuum_loss_cold`` and
    ``calibrated_sensor_fault`` channel lists came back as a substituted string,
    with no diagnostic and no refusal -- so the alarm engine would arm on
    channels that do not exist.

    Recorded because the miss matters: an earlier version of the OC-040 row said
    the post-import ordering was CLOSED, when three loaders had been fixed and
    this fourth one had not been looked for.  Fixing instances of a class is not
    the same as closing the class, and the register said the stronger thing.
    """

    probe = (
        "from cryodaq.core.alarm_config import load_alarm_config\n"
        + CHANNEL_POISON
        + "import pathlib\n"
        + f"loaded = load_alarm_config(pathlib.Path({str(SHIPPED_ALARM_CONFIG)!r}))\n"
        + "engine, alarms = loaded\n"
        + 'assert alarms, "no alarms parsed -- an empty result is an absent measurement, not a pass"\n'
        + 'print("POISONED" if "POISONED" in repr(loaded) else "CLEAN")\n'
    )
    assert _run(probe) == "CLEAN"


def test_production_loader_still_refuses_duplicate_keys(tmp_path: Path) -> None:
    """Moving the loader to module level must not drop the refusal it carried.

    ``add_constructor`` now runs once at import rather than on every call, so
    this asserts the behaviour survived the move rather than assuming it did.
    """

    from cryodaq.core.physical_alarms_config import (
        PhysicalAlarmsConfigError,
        load_production_physical_alarms_config,
    )

    document = tmp_path / "physical_alarms.yaml"
    shipped = SHIPPED_ALARMS_CONFIG.read_text(encoding="utf-8")
    document.write_text(shipped + "\nvacuum:\n  enabled: true\n", encoding="utf-8")
    with pytest.raises(PhysicalAlarmsConfigError, match="duplicate"):
        load_production_physical_alarms_config(document)


def test_library_registration_before_import_is_a_disclosed_limit(tmp_path: Path) -> None:
    """The other ordering is NOT closed, and this test says so out loud.

    The owned tables are copied at class-definition time, which is import time.
    A library imported ahead of ``cryodaq.core`` that registers at its own
    import time has its value copied in.  This is a real gap and not merely a
    hostile one -- it happens by import ordering, without intent.  Closing it
    needs constructors DEFINED IN THE PACKAGE rather than copied, as
    ``cryodaq.lab_profile`` does; that is a larger change to loaders whose
    vocabulary must stay wide, and it is deliberately not attempted here.

    This test exists so the limit cannot quietly stop being true in either
    direction.  If a later change closes it, this test fails, and the
    disclosure that rides with it must be updated rather than forgotten.
    """

    document = tmp_path / "physical_alarms.yaml"
    document.write_text(ALARMS_DOCUMENT, encoding="utf-8")
    assert _run(_alarms_probe(document, "pre")) == "POISONED"


@pytest.mark.parametrize(
    ("module_name", "loader_name"),
    [
        ("cryodaq.storage.channel_descriptors", "_StrictDescriptorLoader"),
        ("cryodaq.periodic_config", "_StrictSafeLoader"),
        ("cryodaq.core.physical_alarms_config", "_OwnedSafeLoader"),
        ("cryodaq.core.physical_alarms_config", "_UniqueSafeLoader"),
    ],
)
def test_each_loader_resists_registration_after_import(module_name: str, loader_name: str) -> None:
    """Every owned loader, exercised through the loader the product actually uses."""

    probe = _ordered(
        f"from {module_name} import {loader_name}\n",
        "import yaml\n"
        f'value = yaml.load("channel: 12K\\n", Loader={loader_name})\n'
        'print("POISONED" if "POISONED" in repr(value) else "CLEAN")\n',
        order="post",
    )
    assert _run(probe) == "CLEAN"


@pytest.mark.parametrize(
    ("module_name", "loader_name"),
    [
        ("cryodaq.storage.channel_descriptors", "_StrictDescriptorLoader"),
        ("cryodaq.periodic_config", "_StrictSafeLoader"),
        ("cryodaq.core.physical_alarms_config", "_OwnedSafeLoader"),
        ("cryodaq.core.physical_alarms_config", "_UniqueSafeLoader"),
    ],
)
def test_no_parsing_table_is_shared_with_yaml_safeloader(module_name: str, loader_name: str) -> None:
    """A structural cross-check of the behavioural tests above.

    Deliberately NOT the primary evidence: on its own this is satisfiable by a
    defective loader, because ``add_constructor`` copies on write, so the
    identity differs while the CONTENT was copied from a poisoned table.  It
    earns its place only as a check that the owned mutable tables were covered
    rather than the one that was noticed first.
    """

    loader = getattr(__import__(module_name, fromlist=[loader_name]), loader_name)
    for table in (
        "yaml_constructors",
        "yaml_multi_constructors",
        "yaml_implicit_resolvers",
        "yaml_path_resolvers",
        "bool_values",
        "ESCAPE_REPLACEMENTS",
        "ESCAPE_CODES",
        "DEFAULT_TAGS",
    ):
        assert getattr(loader, table) is not getattr(yaml.SafeLoader, table), table


def test_post_import_poison_of_escape_and_inf_state_cannot_reach_the_owned_loader() -> None:
    """The FULL parser state is owned, not just the five constructor tables.

    ``OwnedSafeLoader`` copies the scanner's ``ESCAPE_REPLACEMENTS`` table and
    the constructor's ``inf_value`` at import, exactly like the five table
    copies.  A host mutating ``yaml.SafeLoader.ESCAPE_REPLACEMENTS`` or
    rebinding ``yaml.SafeLoader.inf_value`` AFTER this module imports must not
    change what ``owned_safe_load`` parses.  Before the fix, mutating the escape
    table substituted ``a\\nb`` and rebinding ``inf_value`` made ``.inf`` parse
    as the integer ``1`` -- both silent, both on the safety-bearing entry point
    this module provides.
    """

    probe = (
        "from cryodaq._owned_yaml import owned_safe_load\n"
        "import yaml\n"
        'yaml.SafeLoader.ESCAPE_REPLACEMENTS["n"] = "SUBSTITUTED"\n'
        "yaml.SafeLoader.inf_value = 1\n"
        "escape = owned_safe_load('value: \"a\\\\nb\"')\n"
        "inf = owned_safe_load('v: .inf')\n"
        'print("POISONED" if "SUBSTITUTED" in repr(escape) or inf["v"] == 1 else "CLEAN")\n'
    )
    assert _run(probe) == "CLEAN"


@pytest.mark.parametrize(
    ("module_name", "loader_name"),
    [
        ("cryodaq.storage.channel_descriptors", "_StrictDescriptorLoader"),
        ("cryodaq.periodic_config", "_StrictSafeLoader"),
        ("cryodaq.core.physical_alarms_config", "_OwnedSafeLoader"),
        ("cryodaq.core.physical_alarms_config", "_UniqueSafeLoader"),
    ],
)
def test_every_fixed_loader_derives_from_the_one_shared_owner(module_name: str, loader_name: str) -> None:
    """The register claims these share ONE owned loader; this makes that checkable.

    Two of them used to repeat the table copies locally instead of inheriting
    them.  That reads as equivalent and is not: the whole point of the shared
    class is that a later hardening -- replacing its copied tables with
    package-owned pristine constructors, which is what OC-040 requires to close
    -- reaches every loader at once.  A local copy would silently stay on the
    old, pre-import-poisonable path while the register recorded the class as
    handled, which is the failure mode this row has already produced once.
    """

    from cryodaq._owned_yaml import OwnedSafeLoader

    loader = getattr(__import__(module_name, fromlist=[loader_name]), loader_name)
    assert issubclass(loader, OwnedSafeLoader), f"{module_name}.{loader_name} does not share the owned loader"


def test_the_owned_vocabulary_is_not_narrowed() -> None:
    """Owning the tables must not change what parses.

    The vocabulary is deliberately NOT narrowed here, unlike
    ``cryodaq.lab_profile``: a tag census over the shipped configs shows they
    require float, so dropping constructors would reject legitimate lab
    configuration.  The defect is shared mutable STATE, not an over-broad
    grammar, and the fix should be invisible to every valid document.
    """

    from cryodaq.core.physical_alarms_config import _OwnedSafeLoader

    assert set(_OwnedSafeLoader.yaml_constructors) == set(yaml.SafeLoader.yaml_constructors)
    for tag, constructor in yaml.SafeLoader.yaml_constructors.items():
        assert _OwnedSafeLoader.yaml_constructors[tag] is constructor, tag
