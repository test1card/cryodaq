# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for CryoDAQ.

Build:
    pyinstaller build_scripts/cryodaq.spec --clean --noconfirm

Produces ``dist/CryoDAQ/CryoDAQ[.exe]`` in ONEDIR mode. ONEDIR is required
because the engine spawns multiprocessing child processes for the ZMQ bridge;
``--onefile`` breaks ``spawn`` on Windows.

Entry point is ``cryodaq/_frozen_main.py`` which calls
``multiprocessing.freeze_support()`` BEFORE any heavy imports — see Phase 1
DEEP_AUDIT_CC.md E.2 for the Windows fork bomb explanation.

Configs and data live NEXT TO the exe, not inside ``_MEIPASS``. ``paths.py``
detects ``sys.frozen`` and resolves against ``sys.executable.parent``.
"""
from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

PROJECT_ROOT = Path(SPECPATH).parent  # noqa: F821 — SPECPATH injected by PyInstaller

block_cipher = None

# Entry point uses _dispatch() (the file's __main__) which inspects --mode=...
# argv to route to engine / gui / launcher. The launcher re-spawns itself with
# the appropriate flag in frozen mode.
entry_point = str(PROJECT_ROOT / "src" / "cryodaq" / "_frozen_main.py")

hidden_imports = [
    # PySide6 modules we actually use
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    # pyqtgraph
    "pyqtgraph",
    "pyqtgraph.Qt",
    "pyqtgraph.canvas",
    # ZMQ
    "zmq",
    "zmq.backend.cython",
    "zmq.utils",
    "zmq.utils.strtypes",
    "zmq.utils.jsonapi",
    # Serial
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
    "serial.tools.list_ports_windows",
    "serial.tools.list_ports_linux",
    "serial.tools.list_ports_osx",
    "serial_asyncio",
    # pyvisa — backend loaded via entry points at runtime
    "pyvisa",
    "pyvisa.ctwrapper",
    "pyvisa.resources",
    "pyvisa_py",
    # Scientific stack
    "numpy",
    "scipy",
    "scipy.stats",
    "scipy.special",
    "scipy.special._ufuncs_cxx",
    # h5py
    "h5py",
    "h5py.defs",
    "h5py.utils",
    "h5py._proxy",
    # msgpack (C extension)
    "msgpack",
    "msgpack._cmsgpack",
    # matplotlib (used in periodic reports)
    "matplotlib",
    "matplotlib.backends.backend_agg",
    # docx for reports
    "docx",
    # Our own dynamically-loaded modules
    "cryodaq.engine",
    "cryodaq.launcher",
    "cryodaq.gui.app",
    "cryodaq.gui.main_window",
    "cryodaq.drivers.instruments.lakeshore_218s",
    "cryodaq.drivers.instruments.keithley_2604b",
    "cryodaq.drivers.instruments.thyracont_vsp63d",
    "cryodaq.analytics.plugin_loader",
    "cryodaq.core.safety_manager",
    "cryodaq.core.scheduler",
    "cryodaq.storage.sqlite_writer",
]

# Collect every cryodaq submodule (catches anything we missed above).
hidden_imports += collect_submodules("cryodaq")

# datas: files bundled INSIDE the _MEIPASS dir (read-only constants).
# Configs, plugins and runtime data live NEXT TO the exe and are seeded by
# build_scripts/post_build.py.
datas = [
    (str(PROJECT_ROOT / "tsp"), "tsp"),  # Lua scripts (read-only constants)
]
datas += collect_data_files("PySide6")

binaries = []

a = Analysis(
    [entry_point],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy unused Qt modules.
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtBluetooth",
        "PySide6.QtLocation",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNfc",
        "PySide6.QtPdf",
        "PySide6.QtPositioning",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQuickWidgets",
        "PySide6.QtSensors",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
        # Unused
        "tkinter",
        "test",
        "tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CryoDAQ",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX breaks PySide6 on Windows
    console=True,  # Keep console for log visibility in Phase 1; hide in Phase 2
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CryoDAQ",
)
