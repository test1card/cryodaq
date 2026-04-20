"""Tests for XML 1.0 compatibility sanitizer."""

from cryodaq.utils.xml_safe import xml_safe


class TestXmlSafe:
    def test_null_byte_stripped(self):
        # The production bug: Keithley VISA serial termination
        keithley_resource = "USB0::0x05E6::0x2604::4083236\x00::0::INSTR"
        result = xml_safe(keithley_resource)
        assert "\x00" not in result
        assert result == "USB0::0x05E6::0x2604::4083236::0::INSTR"

    def test_all_c0_controls_except_tab_lf_cr_stripped(self):
        text = "a\x01b\x08c\x0bd\x0ce\x0ff\x1fg"
        assert xml_safe(text) == "abcdefg"

    def test_preserves_tab_lf_cr(self):
        # These ARE valid in XML 1.0
        assert xml_safe("a\tb\nc\rd") == "a\tb\nc\rd"

    def test_preserves_printable_ascii(self):
        s = "Hello, World! 123 []{}()"
        assert xml_safe(s) == s

    def test_preserves_cyrillic(self):
        s = "Температура криостата: 4.2 К"
        assert xml_safe(s) == s

    def test_preserves_unicode_symbols(self):
        s = "± ∞ √ → — μ°"
        assert xml_safe(s) == s

    def test_none_returns_empty_string(self):
        assert xml_safe(None) == ""

    def test_non_str_coerced(self):
        assert xml_safe(123) == "123"
        assert xml_safe(3.14) == "3.14"
        assert xml_safe(True) == "True"

    def test_empty_string(self):
        assert xml_safe("") == ""

    def test_del_0x7f_stripped(self):
        assert xml_safe("a\x7fb") == "ab"
