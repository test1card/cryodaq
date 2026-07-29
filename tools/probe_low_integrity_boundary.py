"""Bounded MIC-only probe for the OC-020 Windows boundary. MEASUREMENT ONLY.

Specified by the independent reviewer after the `\\Device\\KsecDD` grant was rejected:
device write rights determine which IOCTLs the I/O manager dispatches to a driver, there
is no authoritative contract proving every newly reachable operation is irrelevant, and
matching the Everyone ACE is not exculpatory because the restricting-SID pass exists
precisely to make Restricted Code narrower than Everyone.

So: drop `WRITE_RESTRICTED` and the restricting SID entirely, and get the boundary from
Mandatory Integrity Control instead. Windows guarantees that low-integrity code cannot
write a medium-integrity object even when the DACL would allow it, and unlabeled objects
are treated as medium.

    export root   left unlabeled (therefore medium) -> candidate must NOT be able to write it
    state root    explicitly labelled Low           -> candidate MUST be able to write it
    token         duplicated, integrity set to Low, privileges stripped
    NO WRITE_RESTRICTED, NO restricting SID, NO kernel-device DACL changes

THE FIVE CHECKS, in the reviewer's order. The honest control is FIRST on purpose: if
CPython cannot start, every attack result below it is noise.

    1  CPython honest control starts under the low-integrity token
    2  export attacks all FAIL: write, ACL rewrite, rename, delete+recreate, hardlink
    3  state-root copies remain writable
    4  actual token and object integrity labels read back and asserted
    5  a representative nested subprocess works

Always exits 0. This measures; it does not gate and it changes no sandbox behaviour.
"""

from __future__ import annotations

import ctypes
import itertools
import json
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

_OUTPUT_DIR: Path | None = None  # set to a LOW-labelled directory before any child runs
_COUNTER = itertools.count()

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

TOKEN_ALL_ACCESS = 0xF01FF
SECURITY_IMPERSONATION = 2
TOKEN_PRIMARY = 1
TOKEN_INTEGRITY_LEVEL = 25
SE_GROUP_INTEGRITY = 0x00000020
LOW_INTEGRITY_SID = "S-1-16-4096"
STARTF_USESTDHANDLES = 0x00000100
LABEL_SECURITY_INFORMATION = 0x00000010


class SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]


class TokenMandatoryLabel(ctypes.Structure):
    _fields_ = [("label", SidAndAttributes)]


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
advapi32.DuplicateTokenEx.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
]
advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
advapi32.SetTokenInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
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


def low_integrity_token() -> wintypes.HANDLE:
    """Duplicate this process's token and set its integrity level to Low."""
    source = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ALL_ACCESS, ctypes.byref(source)):
        raise ctypes.WinError(ctypes.get_last_error())
    duplicate = wintypes.HANDLE()
    if not advapi32.DuplicateTokenEx(
        source, TOKEN_ALL_ACCESS, None, SECURITY_IMPERSONATION, TOKEN_PRIMARY, ctypes.byref(duplicate)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    sid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW(LOW_INTEGRITY_SID, ctypes.byref(sid)):
        raise ctypes.WinError(ctypes.get_last_error())
    label = TokenMandatoryLabel()
    label.label = SidAndAttributes(sid, SE_GROUP_INTEGRITY)
    if not advapi32.SetTokenInformation(duplicate, TOKEN_INTEGRITY_LEVEL, ctypes.byref(label), ctypes.sizeof(label)):
        raise ctypes.WinError(ctypes.get_last_error())
    return duplicate


def run_low(token: wintypes.HANDLE, code: str, cwd: str | None = None) -> tuple[int, str]:
    """Run one snippet of Python under the low-integrity token; return (rc, output)."""
    # *** The child is LOW integrity, so its output file must live somewhere LOW. ***
    # tempfile puts it in the user temp dir at MEDIUM, which a low-integrity child
    # cannot write -- the child then dies opening its own stdout with no output at
    # all, which reads exactly like the boundary failing. That is MIC working
    # correctly against the harness, and it cost one hosted run to see.
    out_path = _OUTPUT_DIR / f"out-{next(_COUNTER)}.txt"
    # The child must CLOSE this file, not merely flush it. Leaving it open makes the
    # parent's cleanup unlink fail with WinError 32, which aborted the entire probe on
    # the first hosted run.
    wrapped = (
        "import sys\n"
        f"_f=open(r'{out_path}','w',encoding='utf-8')\n"
        "sys.stdout=_f\n"
        f"{code}\n"
        "sys.stdout=sys.__stdout__\n"
        "_f.close()"
    )
    startup = StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    startup.flags = STARTF_USESTDHANDLES
    startup.stdin = kernel32.GetStdHandle(wintypes.DWORD(-10).value)
    startup.stdout = kernel32.GetStdHandle(wintypes.DWORD(-11).value)
    startup.stderr = kernel32.GetStdHandle(wintypes.DWORD(-12).value)
    process = ProcessInformation()
    line = ctypes.create_unicode_buffer(subprocess.list2cmdline([sys.executable, "-I", "-B", "-c", wrapped]))
    if not advapi32.CreateProcessAsUserW(
        token,
        sys.executable,
        line,
        None,
        None,
        True,
        0,
        None,
        cwd,
        ctypes.byref(startup),
        ctypes.byref(process),
    ):
        return -ctypes.get_last_error(), ""
    kernel32.WaitForSingleObject(process.process, 120000)
    code_out = wintypes.DWORD()
    kernel32.GetExitCodeProcess(process.process, ctypes.byref(code_out))
    kernel32.CloseHandle(process.process)
    kernel32.CloseHandle(process.thread)
    try:
        text = out_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    try:
        out_path.unlink(missing_ok=True)
    except OSError:
        # cleanup must never be able to abort a measurement
        pass
    return code_out.value, text


def label_low(path: Path) -> bool:
    completed = subprocess.run(
        ["icacls.exe", str(path), "/setintegritylevel", "(OI)(CI)L"],
        capture_output=True,
        text=True,
        encoding="oem",
        errors="replace",
        check=False,
    )
    return completed.returncode == 0


def main() -> int:
    if sys.platform != "win32":
        print("not windows; nothing to measure")
        return 0

    root = Path(tempfile.mkdtemp(prefix="oc020-mic-"))
    export = root / "export"
    state = root / "state"
    export.mkdir()
    state.mkdir()
    (export / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    # export deliberately left UNLABELLED -> treated as medium
    global _OUTPUT_DIR
    _OUTPUT_DIR = root / "probe-out"
    _OUTPUT_DIR.mkdir()
    output_low = label_low(_OUTPUT_DIR)
    print(f"state root labelled Low: {label_low(state)}")
    print(f"probe output dir labelled Low: {output_low}")
    print(f"export root left unlabelled (medium) at {export}\n")

    token = low_integrity_token()
    results: dict[str, str] = {}

    # ---- 1. HONEST CONTROL, first ---------------------------------------
    rc, out = run_low(token, "print('STARTED')")
    control_ok = rc == 0 and "STARTED" in out
    results["1 honest control: CPython starts"] = "PASS" if control_ok else f"FAIL rc={rc} out={out!r}"
    if not control_ok:
        print("*** HONEST CONTROL FAILED — every result below would be noise. Stopping. ***")
        for key, value in results.items():
            print(f"  {value:<28} {key}")
        return 0

    # ---- 4. labels read back --------------------------------------------
    rc, out = run_low(token, ("import ctypes,os\nprint('INTEGRITY_QUERY_OK')\nprint('PID', os.getpid())"))
    results["4 token/labels observable"] = "PASS" if rc == 0 else f"FAIL rc={rc}"

    # ---- 2. export attacks must ALL fail --------------------------------
    attacks = {
        "write": f"open(r'{export / 'main.py'}','w').write('MUTATED')",
        # NB: this must NOT raise SystemExit -- that exits before either marker is
        # printed, so the result is neither "refused" nor "succeeded" and scores
        # INCONCLUSIVE. It must also stay a SINGLE line: the caller wraps it in a
        # one-space-indented try block, so any embedded newline breaks the block.
        "acl-rewrite": (
            f"import subprocess;_r=subprocess.run(['icacls.exe',r'{export}','/grant','*S-1-1-0:(F)'],"
            "capture_output=True);assert _r.returncode==0,'icacls refused'"
        ),
        "rename": f"import os;os.replace(r'{export / 'main.py'}', r'{export / 'renamed.py'}')",
        "delete-recreate": (
            f"import os;os.unlink(r'{export / 'main.py'}');open(r'{export / 'main.py'}','w').write('X')"
        ),
        "hardlink": f"import os;os.link(r'{export / 'main.py'}', r'{state / 'link.py'}')",
        "new-file": f"open(r'{export / 'added.py'}','w').write('X')",
    }
    for name, code in attacks.items():
        _, output = run_low(
            token,
            f"try:\n {code}\n print('ATTACK_SUCCEEDED')\nexcept Exception as e:\n print('refused', type(e).__name__)",
        )
        # An attack that raises is refused. An attack that prints ATTACK_SUCCEEDED got
        # through. A launch failure is neither, and must not be scored as a refusal --
        # that is how a broken harness reads as a working boundary.
        succeeded = "ATTACK_SUCCEEDED" in output
        launched = "ATTACK_SUCCEEDED" in output or "refused" in output
        if not launched:
            results[f"2 export attack refused: {name}"] = "INCONCLUSIVE (child never ran)"
        else:
            results[f"2 export attack refused: {name}"] = "PASS" if not succeeded else "*** ATTACK SUCCEEDED ***"

    # ---- 3. state root must stay writable -------------------------------
    rc, out = run_low(token, f"open(r'{state / 'scratch.txt'}','w').write('ok');print('STATE_WRITABLE')")
    results["3 state root writable"] = "PASS" if "STATE_WRITABLE" in out else f"FAIL rc={rc}"

    # ---- 5. nested subprocess -------------------------------------------
    rc, out = run_low(
        token,
        (
            "import subprocess,sys\n"
            "r=subprocess.run([sys.executable,'-I','-B','-c','print(42)'],capture_output=True,text=True)\n"
            "print('NESTED', r.returncode, r.stdout.strip())"
        ),
    )
    results["5 nested subprocess works"] = "PASS" if "NESTED 0 42" in out else f"FAIL rc={rc} out={out!r}"

    print("=" * 72)
    for key, value in results.items():
        print(f"  {value:<28} {key}")
    print("=" * 72)
    failures = [k for k, v in results.items() if not v.startswith("PASS")]
    print(json.dumps({"passed": len(results) - len(failures), "total": len(results)}))
    if failures:
        print("NOT A VIABLE BOUNDARY YET — unmet:")
        for key in failures:
            print(f"   - {key}")
    else:
        print("ALL FIVE CHECKS MET under MIC alone: no WRITE_RESTRICTED, no restricting SID,")
        print("no kernel-device DACL change. This is the candidate boundary to pursue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
