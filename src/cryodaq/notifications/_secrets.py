"""Minimal SecretStr wrapper to prevent accidental token leaks via repr/str.

Use ``.get_secret_value()`` to obtain the underlying string for use in URLs,
HTTP headers, etc. Never pass a SecretStr to a context that will ``str()`` or
f-string it — use ``.get_secret_value()`` explicitly.

Combined with the ``_TokenRedactFilter`` in ``cryodaq.logging_setup``, this
gives defense-in-depth against the historic Telegram token leak class
(CHANGELOG 0.4.0 had a token committed to git).
"""

from __future__ import annotations


class SecretStr:
    """String wrapper whose ``__repr__`` and ``__str__`` show a mask."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = str(value)

    def get_secret_value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretStr('***')"

    def __str__(self) -> str:
        return "***"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretStr):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)

    def __len__(self) -> int:
        return len(self._value)
