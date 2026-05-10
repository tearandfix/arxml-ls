from lxml import etree

from arxml_ls.analysis import (
    extract_reference_from_line,
    extract_reference_path,
    find_node_by_short_name_line,
    find_reference_span_in_line,
    get_path_segment_at_cursor,
    get_short_name_at_position,
    is_reference_tag,
    locate_reference_span,
)


class TestIsReferenceTag:
    def test_ref_suffix(self):
        assert is_reference_tag("COMPONENT-REF") is True

    def test_tref_suffix(self):
        assert is_reference_tag("APPLICATION-TREF") is True

    def test_non_ref_tag(self):
        assert is_reference_tag("SHORT-NAME") is False

    def test_ref_not_at_end(self):
        # Tag must END with -REF or -TREF
        assert is_reference_tag("REF-INVALID") is False

    def test_empty_string(self):
        assert is_reference_tag("") is False


class TestExtractReferencePath:
    def test_valid_ref_tag_returns_path(self):
        elem = etree.fromstring("<COMPONENT-REF>/Application/Comp</COMPONENT-REF>")
        assert extract_reference_path(elem) == "/Application/Comp"

    def test_strips_whitespace(self):
        elem = etree.fromstring("<COMPONENT-REF>  /Application/Comp  </COMPONENT-REF>")
        assert extract_reference_path(elem) == "/Application/Comp"

    def test_non_ref_tag_returns_none(self):
        elem = etree.fromstring("<SHORT-NAME>MyName</SHORT-NAME>")
        assert extract_reference_path(elem) is None

    def test_ref_tag_with_child_elements_returns_none(self):
        elem = etree.fromstring("<COMPONENT-REF><child/></COMPONENT-REF>")
        assert extract_reference_path(elem) is None

    def test_ref_tag_with_empty_text_returns_none(self):
        elem = etree.fromstring("<COMPONENT-REF>   </COMPONENT-REF>")
        assert extract_reference_path(elem) is None

    def test_tref_tag_returns_path(self):
        elem = etree.fromstring(
            '<PROVIDED-INTERFACE-TREF DEST="SERVICE-INTERFACE">/Iface/Svc</PROVIDED-INTERFACE-TREF>'
        )
        assert extract_reference_path(elem) == "/Iface/Svc"


# Reference line used in span tests:
#   <COMPONENT-REF>/Application/Components</COMPONENT-REF>
#   0123456789012345678901234567890123456789012345678901234
#             1111111111222222222233333333334444444444555555
# <COMPONENT-REF> occupies columns 0-14 (15 chars)
# path starts at column 15, ends at column 38 (23 chars: /Application/Components)
_REF_LINE = "<COMPONENT-REF>/Application/Components</COMPONENT-REF>"
_REF_PATH = "/Application/Components"


class TestFindReferenceSpanInLine:
    def test_returns_span_for_matching_path(self):
        assert find_reference_span_in_line(_REF_LINE, _REF_PATH) == (15, 38)

    def test_returns_none_for_different_path(self):
        assert find_reference_span_in_line(_REF_LINE, "/Other/Path") is None

    def test_returns_none_when_no_ref_tag(self):
        assert (
            find_reference_span_in_line("<SHORT-NAME>foo</SHORT-NAME>", "/foo") is None
        )

    def test_returns_none_for_empty_line(self):
        assert find_reference_span_in_line("", _REF_PATH) is None


class TestLocateReferenceSpan:
    def test_finds_span_via_regex_inside_ref_tag(self):
        assert locate_reference_span(_REF_LINE, _REF_PATH) == (15, 38)

    def test_falls_back_to_string_search_when_no_ref_tag(self):
        # "  /Application/Components  " — no XML tag, uses str.find
        line = "  /Application/Components  "
        assert locate_reference_span(line, _REF_PATH) == (2, 25)

    def test_returns_none_when_path_not_found(self):
        assert locate_reference_span("nothing here", _REF_PATH) is None


class TestExtractReferenceFromLine:
    def test_extracts_path_from_ref_tag(self):
        assert extract_reference_from_line(_REF_LINE) == _REF_PATH

    def test_extracts_path_from_tref_tag(self):
        line = "<PROVIDED-INTERFACE-TREF>/Iface/Svc</PROVIDED-INTERFACE-TREF>"
        assert extract_reference_from_line(line) == "/Iface/Svc"

    def test_returns_none_for_non_ref_line(self):
        assert extract_reference_from_line("<SHORT-NAME>Foo</SHORT-NAME>") is None

    def test_returns_none_for_plain_text(self):
        assert extract_reference_from_line("no references here") is None


# Path segment cursor tests use this line:
#   <COMPONENT-REF>/Application/Components/MyComponent</COMPONENT-REF>
#   column:         15          27          38          50
#                   ^           ^           ^           ^
#              path_start  /Components  /MyComponent  path_end
#
# Segment positions (pos_in_path = cursor_col - 15):
#   /  at pos  0 (col 15)  → leading-slash special case → ("/Application", 0)
#   Application: pos 1–11  (col 16–26)  → ("/Application", 0)
#   /  at pos 12 (col 27)  → separator  → ("/Application", 0)
#   Components:  pos 13–22 (col 28–37)  → ("/Application/Components", 1)
#   /  at pos 23 (col 38)  → separator  → ("/Application/Components", 1)
#   MyComponent: pos 24–34 (col 39–49)  → ("/Application/Components/MyComponent", 2)
_SEG_LINE = "<COMPONENT-REF>/Application/Components/MyComponent</COMPONENT-REF>"


class TestGetPathSegmentAtCursor:
    def test_cursor_before_tag_returns_none(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 0) is None

    def test_cursor_on_tag_name_returns_none(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 5) is None

    def test_cursor_on_leading_slash_returns_first_segment(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 15) == ("/Application", 0)

    def test_cursor_on_first_segment_start(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 16) == ("/Application", 0)

    def test_cursor_on_first_segment_end(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 26) == ("/Application", 0)

    def test_cursor_on_separator_after_first_segment(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 27) == ("/Application", 0)

    def test_cursor_on_second_segment_start(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 28) == (
            "/Application/Components",
            1,
        )

    def test_cursor_on_second_segment_end(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 37) == (
            "/Application/Components",
            1,
        )

    def test_cursor_on_separator_after_second_segment(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 38) == (
            "/Application/Components",
            1,
        )

    def test_cursor_on_third_segment_start(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 39) == (
            "/Application/Components/MyComponent",
            2,
        )

    def test_cursor_on_third_segment_end(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 49) == (
            "/Application/Components/MyComponent",
            2,
        )

    def test_cursor_after_closing_tag_returns_none(self):
        assert get_path_segment_at_cursor(_SEG_LINE, 50) is None

    def test_line_without_ref_returns_none(self):
        assert get_path_segment_at_cursor("<SHORT-NAME>Foo</SHORT-NAME>", 5) is None


class TestGetShortNameAtPosition:
    def test_returns_name_and_columns_for_short_name_line(self):
        # "<SHORT-NAME>MyComponent</SHORT-NAME>"
        # group(1) starts at 12, ends at 23
        source = "<SHORT-NAME>MyComponent</SHORT-NAME>"
        assert get_short_name_at_position(source, 0) == ("MyComponent", 12, 23)

    def test_works_with_leading_whitespace(self):
        # "  <SHORT-NAME>X</SHORT-NAME>"
        # group(1) starts at 14, ends at 15
        source = "  <SHORT-NAME>X</SHORT-NAME>"
        assert get_short_name_at_position(source, 0) == ("X", 14, 15)

    def test_multiline_source_uses_correct_line(self):
        source = "other line\n<SHORT-NAME>Comp</SHORT-NAME>"
        assert get_short_name_at_position(source, 1) == ("Comp", 12, 16)

    def test_returns_none_for_non_short_name_line(self):
        source = "<COMPONENT-REF>/App/Comp</COMPONENT-REF>"
        assert get_short_name_at_position(source, 0) is None

    def test_returns_none_for_out_of_bounds_line(self):
        source = "<SHORT-NAME>X</SHORT-NAME>"
        assert get_short_name_at_position(source, 99) is None


class TestFindNodeByShortNameLine:
    # SHORT-NAME sourcelines in conftest.ARXML_SRC (1-indexed per lxml):
    #   Application  → line 4  → line_num 3
    #   Components   → line 7  → line_num 6
    #   MyComponent  → line 10 → line_num 9

    def test_finds_application_node(self, arxml_tree):
        node = find_node_by_short_name_line(arxml_tree, 3)
        assert node is not None
        assert node.name == "Application"

    def test_finds_components_node(self, arxml_tree):
        node = find_node_by_short_name_line(arxml_tree, 6)
        assert node is not None
        assert node.name == "Components"

    def test_finds_leaf_node(self, arxml_tree):
        node = find_node_by_short_name_line(arxml_tree, 9)
        assert node is not None
        assert node.name == "MyComponent"

    def test_returns_none_for_non_short_name_line(self, arxml_tree):
        assert find_node_by_short_name_line(arxml_tree, 99) is None
