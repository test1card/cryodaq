"""Loader trace: WHICH DLL is CPython loading when the restricted token kills it?

INSTRUMENTATION ONLY. Changes no sandbox behaviour, gates nothing, always exits 0.

WHAT IS ALREADY MEASURED, on hosted windows-latest:
  * cmd.exe and git.exe both RUN under the full sandbox token -> not process creation,
    not a System32-only effect;
  * python under privilege-stripping alone RUNS; python under WRITE_RESTRICTED alone
    dies -> the restricting SID S-1-5-12 is the cause, privilege stripping is innocent;
  * S-1-5-12 already holds full access to the window station and desktop -> refuted;
  * granting S-1-5-12 read+execute on the interpreter directory does NOT help -> refuted.

So the open question is narrow: WHAT does CPython's loader touch that a write-restricted
token denies? The child dies at 0xC0000142 with empty stdout and stderr, so it cannot
tell us. A debugger can.

METHOD. Launch the child under the SAME restricted token with DEBUG_PROCESS, then pump
WaitForDebugEvent and record every LOAD_DLL_DEBUG_EVENT (resolving the real path from the
event's file handle, which is far more reliable than reading lpImageName out of the
child's memory), plus any OUTPUT_DEBUG_STRING and EXCEPTION events, until the process
exits. Run the same trace under an UNRESTRICTED token as the control.

**The last DLL loaded before death, and the first divergence between the two traces, is
the answer.** If both traces are identical up to the point the restricted one stops, the
DLL at that boundary is the one whose initialisation fails.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

TOKEN_ACCESS = 0x0001 | 0x0002 | 0x0008 | 0x0020 | 0x0080
WRITE_RESTRICTED = 0x00000008
DEBUG_PROCESS = 0x00000001
DEBUG_ONLY_THIS_PROCESS = 0x00000002
STARTF_USESTDHANDLES = 0x00000100
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
INFINITE = 0xFFFFFFFF

CREATE_PROCESS_EVENT = 3
EXIT_PROCESS_EVENT = 5
LOAD_DLL_EVENT = 6
UNLOAD_DLL_EVENT = 7
OUTPUT_DEBUG_STRING_EVENT = 8
EXCEPTION_EVENT = 1


class SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]


class StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("reserved", wintypes.LPWSTR),
        ("desktop", wintypes.LPWSTR),
        ("title", wintypes.LPWSTR),
        ("x", wintypes.DWORD),
        ("y", wintypes.DWORD),
        ("x_size", wintypes.DWORD),
        ("y_size", wintypes.DWORD),
        ("x_chars", wintypes.DWORD),
        ("y_chars", wintypes.DWORD),
        ("fill", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("show", wintypes.WORD),
        ("cb_reserved2", wintypes.WORD),
        ("reserved2", ctypes.c_void_p),
        ("stdin", wintypes.HANDLE),
        ("stdout", wintypes.HANDLE),
        ("stderr", wintypes.HANDLE),
    ]


class ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("process", wintypes.HANDLE),
        ("thread", wintypes.HANDLE),
        ("process_id", wintypes.DWORD),
        ("thread_id", wintypes.DWORD),
    ]


class ExceptionRecord(ctypes.Structure):
    pass


ExceptionRecord._fields_ = [
    ("code", wintypes.DWORD),
    ("flags", wintypes.DWORD),
    ("record", ctypes.POINTER(ExceptionRecord)),
    ("address", ctypes.c_void_p),
    ("parameter_count", wintypes.DWORD),
    ("parameters", ctypes.c_void_p * 15),
]


class ExceptionDebugInfo(ctypes.Structure):
    _fields_ = [("record", ExceptionRecord), ("first_chance", wintypes.DWORD)]


class LoadDllDebugInfo(ctypes.Structure):
    _fields_ = [
        ("file", wintypes.HANDLE),
        ("base", ctypes.c_void_p),
        ("debug_offset", wintypes.DWORD),
        ("debug_size", wintypes.DWORD),
        ("image_name", ctypes.c_void_p),
        ("unicode", wintypes.WORD),
    ]


class OutputStringDebugInfo(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("unicode", wintypes.WORD), ("length", wintypes.WORD)]


class ExitProcessDebugInfo(ctypes.Structure):
    _fields_ = [("exit_code", wintypes.DWORD)]


class DebugEventUnion(ctypes.Union):
    _fields_ = [
        ("exception", ExceptionDebugInfo),
        ("load_dll", LoadDllDebugInfo),
        ("output_string", OutputStringDebugInfo),
        ("exit_process", ExitProcessDebugInfo),
        ("padding", ctypes.c_byte * 176),
    ]


class DebugEvent(ctypes.Structure):
    _fields_ = [
        ("code", wintypes.DWORD),
        ("process_id", wintypes.DWORD),
        ("thread_id", wintypes.DWORD),
        ("u", DebugEventUnion),
    ]


advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
advapi32.CreateRestrictedToken.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(SidAndAttributes),
    ctypes.POINTER(wintypes.HANDLE),
]
advapi32.CreateProcessAsUserW.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.LPCWSTR,
    ctypes.POINTER(StartupInfo),
    ctypes.POINTER(ProcessInformation),
]
kernel32.WaitForDebugEvent.argtypes = [ctypes.POINTER(DebugEvent), wintypes.DWORD]
kernel32.ContinueDebugEvent.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
kernel32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
kernel32.GetStdHandle.restype = wintypes.HANDLE


def token(*, restrict: bool) -> wintypes.HANDLE:
    process_token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ACCESS, ctypes.byref(process_token)):
        raise ctypes.WinError(ctypes.get_last_error())
    sid = ctypes.c_void_p()
    advapi32.ConvertStringSidToSidW("S-1-5-12", ctypes.byref(sid))
    restricting = SidAndAttributes(sid, 0)
    out = wintypes.HANDLE()
    if not advapi32.CreateRestrictedToken(
        process_token,
        WRITE_RESTRICTED if restrict else 0,
        0,
        None,
        0,
        None,
        1 if restrict else 0,
        ctypes.byref(restricting) if restrict else None,
        ctypes.byref(out),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return out


def dll_path(handle: int) -> str:
    if not handle:
        return "<no file handle>"
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetFinalPathNameByHandleW(handle, buffer, 32768, 0)
    return buffer.value if length else "<unresolved>"


def trace(label: str, *, restrict: bool) -> list[str]:
    print(f"===== {label} =====")
    startup = StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    startup.flags = STARTF_USESTDHANDLES
    startup.stdin = kernel32.GetStdHandle(wintypes.DWORD(-10).value)
    startup.stdout = kernel32.GetStdHandle(wintypes.DWORD(-11).value)
    startup.stderr = kernel32.GetStdHandle(wintypes.DWORD(-12).value)
    process = ProcessInformation()
    argv = [sys.executable, "-I", "-B", "-c", "raise SystemExit(7)"]
    line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))

    if not advapi32.CreateProcessAsUserW(
        token(restrict=restrict),
        sys.executable,
        line,
        None,
        None,
        True,
        DEBUG_PROCESS | DEBUG_ONLY_THIS_PROCESS,
        None,
        None,
        ctypes.byref(startup),
        ctypes.byref(process),
    ):
        print(f"  CreateProcessAsUser failed, win32 error {ctypes.get_last_error()}")
        return []

    loaded: list[str] = []
    event = DebugEvent()
    exit_code = None
    while True:
        if not kernel32.WaitForDebugEvent(ctypes.byref(event), 60000):
            print("  WaitForDebugEvent timed out")
            break
        status = DBG_CONTINUE
        if event.code == LOAD_DLL_EVENT:
            path = dll_path(event.u.load_dll.file)
            loaded.append(path)
            print(f"  LOAD  {path}")
        elif event.code == EXCEPTION_EVENT:
            record = event.u.exception.record
            first = "first-chance" if event.u.exception.first_chance else "second-chance"
            print(f"  EXCEPTION 0x{record.code & 0xFFFFFFFF:08X} ({first}) at {record.address}")
            if record.code & 0xFFFFFFFF not in (0x80000003, 0x4000001F):
                status = DBG_EXCEPTION_NOT_HANDLED
        elif event.code == OUTPUT_DEBUG_STRING_EVENT:
            print("  OUTPUT_DEBUG_STRING emitted by the child")
        elif event.code == EXIT_PROCESS_EVENT:
            exit_code = event.u.exit_process.exit_code
            print(f"  EXIT  code {exit_code} (0x{exit_code & 0xFFFFFFFF:08X})")
        kernel32.ContinueDebugEvent(event.process_id, event.thread_id, status)
        if event.code == EXIT_PROCESS_EVENT:
            break

    print(f"  -> {len(loaded)} DLLs loaded before exit\n")
    return loaded


def main() -> int:
    if sys.platform != "win32":
        print("not windows; nothing to trace")
        return 0

    control = trace("CONTROL: unrestricted token", restrict=False)
    restricted = trace("RESTRICTED: WRITE_RESTRICTED + S-1-5-12", restrict=True)

    print("=" * 72)
    if not control:
        print("CONTROL DID NOT RUN — nothing below is interpretable.")
        return 0
    print(f"control loaded {len(control)} DLLs; restricted loaded {len(restricted)}")
    divergence = None
    for index, name in enumerate(control):
        if index >= len(restricted):
            divergence = name
            break
        if restricted[index].lower() != name.lower():
            divergence = f"{name}  (restricted loaded {restricted[index]} instead)"
            break
    if divergence:
        print()
        print("*** FIRST DIVERGENCE — the restricted child stopped needing/reaching: ***")
        print(f"    {divergence}")
        if restricted:
            print(f"    last DLL it DID load: {restricted[-1]}")
    else:
        print("No divergence in the DLL sequence: the restricted child loaded the same set.")
        print("The failure is then AFTER load, inside an initialiser, not at load time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
