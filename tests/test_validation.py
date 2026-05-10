from lxml import etree

from arxml_ls.validation import parse_arxml


class TestParseArxml:
    def test_returns_none_for_valid_xml(self):
        assert parse_arxml("<root><child/></root>") is None

    def test_returns_error_for_mismatched_tags(self):
        error = parse_arxml("<root><child></root>")
        assert isinstance(error, etree.XMLSyntaxError)

    def test_returns_error_for_unclosed_tag(self):
        error = parse_arxml("<root><child>")
        assert isinstance(error, etree.XMLSyntaxError)

    def test_error_has_line_number(self):
        error = parse_arxml("<root>\n<bad></root>")
        assert error is not None
        assert error.lineno is not None
        assert error.lineno > 0

    def test_returns_none_for_arxml_like_xml(self):
        xml = (
            "<AUTOSAR>"
            "<AR-PACKAGES>"
            "<AR-PACKAGE><SHORT-NAME>App</SHORT-NAME></AR-PACKAGE>"
            "</AR-PACKAGES>"
            "</AUTOSAR>"
        )
        assert parse_arxml(xml) is None
