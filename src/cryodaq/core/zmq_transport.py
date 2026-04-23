from __future__ import annotations

import errno
import os
import socket
import stat
import sys
from pathlib import Path


def _default_transport_addrs() -> tuple[str, str]:
    if sys.platform == "win32":
        return ("tcp://127.0.0.1:5555", "tcp://127.0.0.1:5556")
    return ("ipc:///tmp/cryodaq-pub.sock", "ipc:///tmp/cryodaq-cmd.sock")


DEFAULT_PUB_ADDR, DEFAULT_CMD_ADDR = _default_transport_addrs()


def ipc_path(addr: str) -> Path | None:
    if not addr.startswith("ipc://"):
        return None
    return Path(addr[len("ipc://") :])


def tcp_host_port(addr: str) -> tuple[str, int] | None:
    if not addr.startswith("tcp://"):
        return None
    host_port = addr[len("tcp://") :]
    host, port = host_port.rsplit(":", 1)
    return host, int(port)


def _ipc_path_is_live(path: Path) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.1)
        probe.connect(os.fspath(path))
    except OSError as exc:
        if exc.errno in {errno.ECONNREFUSED, errno.ENOENT}:
            return False
        raise FileExistsError(f"Refusing to remove IPC path with unknown state: {path}") from exc
    finally:
        probe.close()
    return True


def _cleanup_ipc_path_if_safe(path: Path) -> None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(path_stat.st_mode):
        raise FileExistsError(f"Refusing to remove non-socket IPC path: {path}")
    if _ipc_path_is_live(path):
        raise FileExistsError(f"Refusing to remove live IPC endpoint: {path}")
    os.unlink(path)


def prepare_ipc_path(addr: str) -> None:
    path = ipc_path(addr)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_ipc_path_if_safe(path)


def cleanup_ipc_path(addr: str) -> None:
    path = ipc_path(addr)
    if path is None:
        return
    _cleanup_ipc_path_if_safe(path)
