"""Discriminate the OC-020 Windows failure. INSTRUMENTATION ONLY — changes no sandbox behaviour.

The candidate sandbox builds a restricted token — CreateRestrictedToken(WRITE_RESTRICTED)
with restricting SID S-1-5-12 (RESTRICTED CODE), all privileges removed except
SeChangeNotifyPrivilege and SeCreateSymbolicLinkPrivilege — and launches its child with
CreateProcessAsUserW. On windows-latest the child exits 3221225794 = 0xC0000142 =
STATUS_DLL_INIT_FAILED with EMPTY stdout and stderr: it dies during DLL initialisation,
before any Python code runs, and reports nothing.

WHAT IS ALREADY ELIMINATED. The obvious hypothesis was window station / desktop access:
Microsoft documents that a restricted token may need those DACLs widened, and that failure
presents exactly this way. It is REFUTED — S-1-5-12 (SDDL abbreviation `RC`) holds full
access to both objects. `ConvertStringSidToSidW("RC") -> S-1-5-12` confirms the mapping.

WHY THIS RUNS HERE AND NOT ON A DEVELOPER MACHINE. The same experiment run locally failed
at CreateProcessAsUserW with ACCESS_DENIED for every target, because that shell's token
holds ZERO privileges and therefore lacks SeAssignPrimaryTokenPrivilege. It could not create
the process at all, so it discriminated nothing. GitHub's windows-latest runner is
administrative, so the process can actually be created and the failure observed.

THE DISCRIMINATION. Three targets of increasing loader weight, launched through the exact
call shape the sandbox uses:

    A  cmd.exe /c exit 7      minimal loader, no CRT, no Python
    B  python -c ...          full CPython loader
    C  python -I -B -c ...    isolated mode, as the sandbox invokes its child

    A ok, B/C 0xC0000142   -> the fault is what CPython's loader does under a
                              write-restricted token, not process creation
    all three 0xC0000142   -> fundamental to the token itself
    all three ok           -> the token is fine and the fault is in the sandbox's own
                              child script, which would be the most useful answer of all

It also reports the token's privilege count and the restricting-SID state, so the result is
interpretable without re-deriving the setup.

Exit code is always 0: this is a measurement, not a gate.
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
SE_PRIVILEGE_ENABLED = 0x00000002
SE_PRIVILEGE_REMOVED = 0x00000004
STARTF_USESTDHANDLES = 0x00000100
DLL_INIT_FAILED = 3221225794
RETAIN = ("SeChangeNotifyPrivilege", "SeCreateSymbolicLinkPrivilege")


class Luid(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]


class LuidAndAttributes(ctypes.Structure):
    _fields_ = [("luid", Luid), ("attributes", wintypes.DWORD)]


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


advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(Luid)]
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
kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
kernel32.GetStdHandle.restype = wintypes.HANDLE


def privilege_count(token: wintypes.HANDLE) -> int:
    needed = wintypes.DWORD()
    advapi32.GetTokenInformation(token, 3, None, 0, ctypes.byref(needed))
    if not needed.value:
        return -1
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.GetTokenInformation(token, 3, buffer, needed.value, ctypes.byref(needed)):
        return -1
    return ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value


def build_token(*, restrict: bool = True, strip: bool = True) -> wintypes.HANDLE:
    """The sandbox's token. restrict/strip isolate its two mechanisms."""
    process_token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ACCESS, ctypes.byref(process_token)):
        raise ctypes.WinError(ctypes.get_last_error())
    print(f"caller process token privileges: {privilege_count(process_token)}")

    sid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW("S-1-5-12", ctypes.byref(sid)):
        raise ctypes.WinError(ctypes.get_last_error())
    restricting = SidAndAttributes(sid, 0)
    restricted = wintypes.HANDLE()
    if not advapi32.CreateRestrictedToken(
        process_token,
        WRITE_RESTRICTED if restrict else 0,
        0,
        None,
        0,
        None,
        1 if restrict else 0,
        ctypes.byref(restricting) if restrict else None,
        ctypes.byref(restricted),
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    count = privilege_count(restricted) if strip else 0
    print(f"restricted token privileges before stripping: {count}")
    if count > 0:
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(restricted, 3, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        advapi32.GetTokenInformation(restricted, 3, buffer, needed.value, ctypes.byref(needed))

        class TokenPrivileges(ctypes.Structure):
            _fields_ = [("count", wintypes.DWORD), ("privileges", LuidAndAttributes * count)]

        privileges = ctypes.cast(buffer, ctypes.POINTER(TokenPrivileges)).contents
        retained: set[tuple[int, int]] = set()
        for name in RETAIN:
            luid = Luid()
            if advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
                retained.add((luid.low, luid.high))
        for privilege in privileges.privileges:
            key = (privilege.luid.low, privilege.luid.high)
            privilege.attributes = SE_PRIVILEGE_ENABLED if key in retained else SE_PRIVILEGE_REMOVED
        ctypes.set_last_error(0)
        advapi32.AdjustTokenPrivileges(restricted, False, ctypes.byref(privileges), 0, None, None)
        print(f"restricted token privileges after stripping:  {privilege_count(restricted)}")
    return restricted


def launch(token: wintypes.HANDLE, application: str, argv: list[str]) -> int:
    startup = StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    startup.flags = STARTF_USESTDHANDLES
    startup.stdin = kernel32.GetStdHandle(wintypes.DWORD(-10).value)
    startup.stdout = kernel32.GetStdHandle(wintypes.DWORD(-11).value)
    startup.stderr = kernel32.GetStdHandle(wintypes.DWORD(-12).value)
    process = ProcessInformation()
    line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
    if not advapi32.CreateProcessAsUserW(
        token,
        application,
        line,
        None,
        None,
        True,
        0,
        None,
        None,
        ctypes.byref(startup),
        ctypes.byref(process),
    ):
        return -ctypes.get_last_error()
    kernel32.WaitForSingleObject(process.process, 60000)
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(process.process, ctypes.byref(code))
    kernel32.CloseHandle(process.process)
    kernel32.CloseHandle(process.thread)
    return code.value


def main() -> int:
    if sys.platform != "win32":
        print("not windows; nothing to measure")
        return 0

    python = [sys.executable, "-I", "-B", "-c", "raise SystemExit(7)"]

    # The sandbox applies TWO mechanisms. A/B/C/D established that the failure is
    # CPython-specific; this isolates WHICH mechanism CPython cannot survive.
    variants = [
        ("1  neither  (control: plain duplicate)", dict(restrict=False, strip=False)),
        ("2  WRITE_RESTRICTED only", dict(restrict=True, strip=False)),
        ("3  privilege stripping only", dict(restrict=False, strip=True)),
        ("4  both      (what the sandbox does)", dict(restrict=True, strip=True)),
    ]

    outcomes = {}
    for label, kwargs in variants:
        print(f"--- {label} ---")
        try:
            token = build_token(**kwargs)
        except OSError as exc:
            print(f"    token construction failed: {exc}")
            outcomes[label[0]] = "notoken"
            continue
        code = launch(token, sys.executable, python)
        if code == 7:
            verdict, kind = "python RAN (exit 7)", "ok"
        elif code == DLL_INIT_FAILED:
            verdict, kind = "*** 0xC0000142 STATUS_DLL_INIT_FAILED ***", "dll"
        elif code < 0:
            verdict, kind = f"CreateProcessAsUser FAILED, win32 error {-code}", "nocreate"
        else:
            verdict, kind = f"ran, exit {code} (0x{code & 0xFFFFFFFF:08X})", "ran"
        outcomes[label[0]] = kind
        print(f"    {verdict}")
        print()

    print("=" * 72)
    restricted_only = outcomes.get("2")
    stripped_only = outcomes.get("3")
    if outcomes.get("1") not in {"ok", "ran"}:
        print("CONTROL FAILED: python does not run even under a plain duplicated token.")
        print("Nothing below is interpretable; the harness itself is at fault.")
    elif restricted_only == "dll" and stripped_only in {"ok", "ran"}:
        print("ISOLATED: WRITE_RESTRICTED alone kills CPython. Privilege stripping is innocent.")
        print("The fix must address the restricting SID's effect on CPython's DLL init.")
    elif stripped_only == "dll" and restricted_only in {"ok", "ran"}:
        print("ISOLATED: privilege STRIPPING alone kills CPython. The restricting SID is innocent.")
        print("CPython's loader needs one of the removed privileges -- identify and retain it.")
    elif restricted_only == "dll" and stripped_only == "dll":
        print("BOTH mechanisms independently kill CPython. Each needs its own fix.")
    else:
        print(f"NEITHER alone reproduces it; only the combination does: {outcomes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
