"""XML 1.0 compatibility sanitizer for python-docx output.

python-docx rejects strings containing characters not allowed in
XML 1.0 (NULL byte, most other C0 control chars). Instrument
metadata like VISA resource strings legitimately contain \x00
for some vendors (e.g. Keithley VISA spec requires null byte
as serial terminator), which breaks report generation when this
metadata is embedded into docx.

Use xml_safe() as a wrapper for any user/config/runtime-sourced
string before passing to python-docx methods.
"""

from __future__ import annotations

import re

# XML 1.0 valid chars: 0x09 (TAB), 0x0A (LF), 0x0D (CR),
# 0x20-0xD7FF, 0xE000-0xFFFD, 0x10000-0x10FFFF.
# Reject: NULL + most C0 controls + DEL (0x7F).
_XML_ILLEGAL_RE = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"
)


def xml_safe(text: object) -> str:
    """Return `text` with XML 1.0 incompatible characters removed.

    None becomes "". Non-str inputs are coerced via str().

    Examples
    --------
    >>> xml_safe("USB0::0x05E6::0x2604::4083236\\x00::0::INSTR")
    'USB0::0x05E6::0x2604::4083236::0::INSTR'
    >>> xml_safe(None)
    ''
    >>> xml_safe("normal text")
    'normal text'
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return _XML_ILLEGAL_RE.sub("", text)
