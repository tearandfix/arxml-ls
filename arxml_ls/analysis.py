import re
from typing import Tuple

from lxml import etree

from .models import ArxmlNode, REF_TAG_PATTERN


def is_reference_tag(tag_name: str) -> bool:
    return tag_name.endswith("-REF") or tag_name.endswith("-TREF")


def extract_reference_path(elem: etree._Element) -> str | None:
    tag_name = elem.tag.split("}")[-1]
    if not is_reference_tag(tag_name):
        return None
    if len(elem):
        return None
    if elem.text:
        ref_path = elem.text.strip()
        if ref_path:
            return ref_path
    return None


def find_reference_span_in_line(
    line_text: str, ref_path: str
) -> Tuple[int, int] | None:
    for match in REF_TAG_PATTERN.finditer(line_text):
        if match.group(1).strip() == ref_path:
            return match.start(1), match.end(1)
    return None


def locate_reference_span(line_text: str, ref_path: str) -> Tuple[int, int] | None:
    span = find_reference_span_in_line(line_text, ref_path)
    if span:
        return span
    idx = line_text.find(ref_path)
    if idx != -1:
        return idx, idx + len(ref_path)
    return None


def extract_reference_from_line(line: str) -> str | None:
    match = REF_TAG_PATTERN.search(line)
    if match:
        return match.group(1).strip()
    return None


def get_path_segment_at_cursor(line: str, cursor_col: int) -> tuple[str, int] | None:
    """Return (partial_path, segment_index) for the path segment under the cursor.

    For a reference like "/Application/Components/MyComponent", if the cursor is on
    "Components" this returns ("/Application/Components", 1).
    """
    match = REF_TAG_PATTERN.search(line)
    if not match:
        return None

    full_path = match.group(1).strip()
    path_start = match.start(1)
    path_end = match.end(1)

    if cursor_col < path_start or cursor_col >= path_end:
        return None

    pos_in_path = cursor_col - path_start

    # Cursor on the leading slash — navigate to first segment
    if pos_in_path == 0 and full_path.startswith("/"):
        path_without_leading_slash = full_path.lstrip("/")
        segments = path_without_leading_slash.split("/")
        if segments:
            return (f"/{segments[0]}", 0)
        return None

    path_without_leading_slash = full_path.lstrip("/")
    segments = path_without_leading_slash.split("/")
    current_pos = 1 if full_path.startswith("/") else 0

    for segment_idx, segment in enumerate(segments):
        segment_start = current_pos
        segment_end = current_pos + len(segment)

        if segment_start <= pos_in_path < segment_end:
            partial_path = "/" + "/".join(segments[: segment_idx + 1])
            return (partial_path, segment_idx)

        if pos_in_path == segment_end and segment_idx < len(segments) - 1:
            partial_path = "/" + "/".join(segments[: segment_idx + 1])
            return (partial_path, segment_idx)

        current_pos = segment_end + 1

    if pos_in_path >= current_pos - 1:
        return (full_path, len(segments) - 1)

    return None


def get_short_name_at_position(
    doc_source: str, line: int
) -> tuple[str, int, int] | None:
    """Return (short_name, start_col, end_col) if the given line contains a SHORT-NAME."""
    lines = doc_source.splitlines()
    if line >= len(lines):
        return None
    line_text = lines[line]
    match = re.search(r"<SHORT-NAME>([^<]+)</SHORT-NAME>", line_text)
    if match:
        return (match.group(1), match.start(1), match.end(1))
    return None


def find_node_by_short_name_line(node: ArxmlNode, line_num: int) -> ArxmlNode | None:
    if hasattr(node.element, "sourceline"):
        for child in node.element:
            child_tag = child.tag.split("}")[-1]
            if child_tag == "SHORT-NAME" and hasattr(child, "sourceline"):
                if child.sourceline == line_num + 1:
                    return node

    for child_node in node.children.values():
        result = find_node_by_short_name_line(child_node, line_num)
        if result:
            return result

    return None
