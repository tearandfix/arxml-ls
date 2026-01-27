#!/usr/bin/env python3
from pygls.server import LanguageServer
from lsprotocol.types import (
    Diagnostic,
    DiagnosticSeverity,
    Position,
    Range,
    Hover,
    MarkupContent,
    MarkupKind,
    SymbolInformation,
    SymbolKind,
    Location,
    TextDocumentPositionParams,
    WorkspaceEdit,
    TextEdit,
    PrepareRenameResult,
)
from lsprotocol import types

from lxml import etree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, cast
from pygls import uris
import re


REF_TAG_PATTERN = re.compile(
    r"<[^>]*?-(?:T?REF)(?![A-Z0-9_-])[^>]*>([^<]+)</[^>]*?-(?:T?REF)(?![A-Z0-9_-])[^>]*>"
)


@dataclass
class ArxmlNode:
    """Represents a node in the ARXML tree structure."""

    name: str  # SHORT-NAME value
    path: str  # Full path from root (e.g., /Application/Executables/Test)
    element: etree._Element  # Reference to the XML element
    children: dict[str, "ArxmlNode"] = field(default_factory=dict)

    def find_by_path(self, path: str) -> "ArxmlNode | None":
        """Find a node by its absolute path."""
        if path == self.path:
            return self

        # Remove leading slash if present
        if path.startswith("/"):
            path = path[1:]

        parts = path.split("/")
        current = self

        for part in parts:
            if part in current.children:
                current = current.children[part]
            else:
                return None

        return current


@dataclass
class ProjectDocument:
    uri: str
    path: Path
    source: str
    root: etree._Element | None = None
    tree: ArxmlNode | None = None
    parse_error: Exception | None = None
    _lines: List[str] | None = field(default=None, init=False, repr=False)

    @property
    def lines(self) -> List[str]:
        if self._lines is None:
            self._lines = self.source.splitlines()
        return self._lines


@dataclass
class ProjectIndex:
    documents: Dict[str, ProjectDocument]
    nodes_by_path: Dict[str, List[Tuple[str, ArxmlNode]]]
    references_by_doc: Dict[str, List[Tuple[etree._Element, str, int, int]]]

    def find_node(self, path: str) -> Tuple[str, ArxmlNode] | None:
        matches = self.nodes_by_path.get(path)
        if matches:
            return matches[0]
        return None

    def path_exists(self, path: str) -> bool:
        return path in self.nodes_by_path


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


def is_reference_tag(tag_name: str) -> bool:
    return tag_name.endswith("-REF") or tag_name.endswith("-TREF")


def extract_reference_path(elem: etree._Element) -> str | None:
    tag_name = elem.tag.split("}")[-1]
    if not is_reference_tag(tag_name):
        return None
    if len(elem):
        # Nested elements are not allowed inside references
        return None
    if elem.text:
        ref_path = elem.text.strip()
        if ref_path:
            return ref_path
    return None


def _get_workspace_root(ls: LanguageServer, fallback_uri: str) -> Path:
    root_path_value = ls.workspace.root_path or ""
    if root_path_value:
        return Path(root_path_value)
    if fallback_uri:
        try:
            return Path(str(uris.to_fs_path(fallback_uri))).parent
        except Exception:
            pass
    return Path.cwd()


def _discover_arxml_files(ls: LanguageServer, fallback_uri: str) -> Dict[str, Path]:
    files: Dict[str, Path] = {}
    workspace_docs = getattr(ls.workspace, "documents", {})

    for doc in workspace_docs.values():
        doc_uri_obj = getattr(doc, "uri", None)
        if doc_uri_obj is None or not isinstance(doc_uri_obj, str):
            continue
        if not doc_uri_obj:
            continue
        try:
            doc_path = Path(str(uris.to_fs_path(doc_uri_obj))).resolve()
            files[doc_uri_obj] = doc_path
        except Exception:
            continue

    root_path = _get_workspace_root(ls, fallback_uri)
    if root_path.exists():
        for path in root_path.glob("*.arxml"):
            resolved = path.resolve()
            uri_value = uris.from_fs_path(str(resolved))
            if not uri_value:
                continue
            files.setdefault(uri_value, resolved)

    # Ensure fallback document is included even if not already tracked
    if fallback_uri:
        try:
            fallback_path = Path(str(uris.to_fs_path(fallback_uri))).resolve()
            files.setdefault(fallback_uri, fallback_path)
        except Exception:
            pass

    return files


def _compute_workspace_state(
    ls: LanguageServer, files: Dict[str, Path]
) -> Tuple[Tuple[str, float | int | None], ...]:
    workspace_docs = getattr(ls.workspace, "documents", {})
    state: List[Tuple[str, float | int | None]] = []

    for uri, path in files.items():
        doc = workspace_docs.get(uri)
        if doc is not None:
            state.append((uri, doc.version))
        else:
            try:
                state.append((uri, path.stat().st_mtime_ns))
            except OSError:
                state.append((uri, None))

    return tuple(sorted(state, key=lambda item: item[0]))


def _register_nodes_for_document(
    doc_uri: str, node: ArxmlNode, registry: Dict[str, List[Tuple[str, ArxmlNode]]]
) -> None:
    for child in node.children.values():
        if child.path:
            registry.setdefault(child.path, []).append((doc_uri, child))
        _register_nodes_for_document(doc_uri, child, registry)


def _build_project_index(ls: LanguageServer, files: Dict[str, Path]) -> ProjectIndex:
    documents: Dict[str, ProjectDocument] = {}
    nodes_by_path: Dict[str, List[Tuple[str, ArxmlNode]]] = {}
    references_by_doc: Dict[str, List[Tuple[etree._Element, str, int, int]]] = {}

    workspace_docs = getattr(ls.workspace, "documents", {})

    for uri, path in files.items():
        source: str | None = None
        doc = workspace_docs.get(uri)
        if doc is not None:
            source = doc.source
        else:
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue

        if source is None:
            continue

        project_doc = ProjectDocument(uri=uri, path=path, source=source)

        try:
            root = etree.fromstring(source.encode("utf-8"))
            tree = build_arxml_tree(root)
            project_doc.root = root
            project_doc.tree = tree
            references_by_doc[uri] = find_all_reference_elements(root)
            _register_nodes_for_document(uri, tree, nodes_by_path)
        except Exception as exc:
            project_doc.parse_error = exc
            references_by_doc[uri] = []

        documents[uri] = project_doc

    return ProjectIndex(
        documents=documents,
        nodes_by_path=nodes_by_path,
        references_by_doc=references_by_doc,
    )


def _get_project_index(ls: LanguageServer, current_uri: str) -> ProjectIndex:
    files = _discover_arxml_files(ls, current_uri)
    state = _compute_workspace_state(ls, files)
    cache = getattr(ls, "_project_index_cache", None)

    if cache and cache.get("state") == state:
        cached_index = cache.get("index")
        if cached_index:
            return cached_index

    index = _build_project_index(ls, files)
    setattr(ls, "_project_index_cache", {"state": state, "index": index})
    return index


class ArxmlLanguageServer(LanguageServer):
    CMD_NAME = "arxml-ls"


server = ArxmlLanguageServer("arxml-ls", "0.1.0")


def build_arxml_tree(root: etree._Element) -> ArxmlNode:
    """Build a tree structure from ARXML element using SHORT-NAME tags."""
    # Create root node
    root_node = ArxmlNode(name="", path="", element=root, children={})

    def process_element(elem: etree._Element, parent_node: ArxmlNode, parent_path: str):
        """Recursively process elements and build tree."""
        # Look for SHORT-NAME child
        short_name = None
        for child in elem:
            tag_name = child.tag.split("}")[-1]  # Remove namespace
            if tag_name == "SHORT-NAME" and child.text:
                short_name = child.text.strip()
                break

        # If this element has a SHORT-NAME, create a node for it
        if short_name:
            node_path = f"{parent_path}/{short_name}"
            node = ArxmlNode(name=short_name, path=node_path, element=elem, children={})
            parent_node.children[short_name] = node

            # Process children with this node as parent
            for child in elem:
                process_element(child, node, node_path)
        else:
            # No SHORT-NAME, continue with same parent
            for child in elem:
                process_element(child, parent_node, parent_path)

    # Process all children of root
    for child in root:
        process_element(child, root_node, "")

    return root_node


def find_all_reference_elements(
    root: etree._Element,
) -> list[tuple[etree._Element, str, int, int]]:
    """Find all reference elements (-REF or -TREF) and their paths.

    Returns:
        List of tuples: (element, reference_path, line_number, column)
    """
    references = []

    for elem in root.iter():
        ref_path = extract_reference_path(elem)
        if ref_path:
            line = elem.sourceline if hasattr(elem, "sourceline") else 0
            column = 0  # lxml doesn't provide column info easily
            references.append((elem, ref_path, line, column))

    return references


def get_path_segment_at_cursor(line: str, cursor_col: int) -> tuple[str, int] | None:
    """Extract the path segment at the cursor position and calculate the target path.

    For a reference like "/Application/Components/MyComponent", if cursor is on "Components",
    this returns ("/Application/Components", segment_index).

    Args:
        line: Line containing the reference
        cursor_col: Column position of cursor (0-indexed)

    Returns:
        Tuple of (partial_path, segment_index) or None if not in a reference

    Example:
        Line: '<REF>/one/two/three</REF>'
        Cursor on "two": Returns ("/one/two", 1)
    """
    # Find the reference pattern and extract path
    match = REF_TAG_PATTERN.search(line)

    if not match:
        return None

    full_path = match.group(1).strip()
    path_start = match.start(1)
    path_end = match.end(1)

    # Check if cursor is within the path
    if cursor_col < path_start or cursor_col >= path_end:
        return None

    # Calculate position within the path string
    pos_in_path = cursor_col - path_start

    # Special case: cursor on the leading slash - navigate to first segment
    if pos_in_path == 0 and full_path.startswith("/"):
        path_without_leading_slash = full_path.lstrip("/")
        segments = path_without_leading_slash.split("/")
        if segments:
            return (f"/{segments[0]}", 0)
        return None

    # Split path into segments
    # Remove leading slash if present
    path_without_leading_slash = full_path.lstrip("/")
    segments = path_without_leading_slash.split("/")

    # Find which segment the cursor is in
    current_pos = 1 if full_path.startswith("/") else 0  # Account for leading slash

    for segment_idx, segment in enumerate(segments):
        segment_start = current_pos
        segment_end = current_pos + len(segment)

        # Check if cursor is within this segment
        if segment_start <= pos_in_path < segment_end:
            # Build partial path up to and including this segment
            partial_segments = segments[: segment_idx + 1]
            partial_path = "/" + "/".join(partial_segments)
            return (partial_path, segment_idx)

        # Check if cursor is on the slash after this segment
        if pos_in_path == segment_end and segment_idx < len(segments) - 1:
            # Cursor on slash - use the segment before the slash
            partial_segments = segments[: segment_idx + 1]
            partial_path = "/" + "/".join(partial_segments)
            return (partial_path, segment_idx)

        # Move to next segment (add 1 for the '/')
        current_pos = segment_end + 1

    # If we're at the end, return the full path
    if pos_in_path >= current_pos - 1:
        return (full_path, len(segments) - 1)

    return None


def extract_reference_from_line(line: str) -> str | None:
    """Extract reference path from a line containing a -REF or -TREF tag.

    Args:
        line: A line of text from the XML file

    Returns:
        The reference path if found, None otherwise

    Example:
        Input: '  <APPLICATION-TYPE-TREF DEST="...">path</APPLICATION-TYPE-TREF>'
        Output: 'path'
    """
    # Pattern to match tags ending in REF or TREF with their content
    # Matches: <TAG-NAME-REF ...>content</TAG-NAME-REF>
    match = REF_TAG_PATTERN.search(line)
    if match:
        return match.group(1).strip()

    return None


def find_all_references_to_path(
    root: etree._Element, target_path: str
) -> list[tuple[etree._Element, int, int]]:
    """Find all reference elements that point to a specific path.

    Args:
        root: The root XML element
        target_path: The path to search for (e.g., '/Application/Components/MyComponent')

    Returns:
        List of tuples: (element, line_number, column)
    """
    matching_refs = []

    for elem in root.iter():
        ref_path = extract_reference_path(elem)
        if ref_path == target_path:
            line = elem.sourceline if hasattr(elem, "sourceline") else 0
            column = 0
            matching_refs.append((elem, line, column))

    return matching_refs


def find_all_references_with_prefix(
    root: etree._Element, path_prefix: str
) -> list[tuple[etree._Element, str, int, int]]:
    """Find all reference elements that start with a specific path prefix.

    This is used to update references when renaming affects child paths.

    Args:
        root: The root XML element
        path_prefix: The path prefix to search for (e.g., '/Application/Components/MyComponent')

    Returns:
        List of tuples: (element, full_ref_path, line_number, column)
    """
    matching_refs = []

    for elem in root.iter():
        ref_path = extract_reference_path(elem)
        if ref_path and ref_path.startswith(path_prefix):
            line = elem.sourceline if hasattr(elem, "sourceline") else 0
            column = 0
            matching_refs.append((elem, ref_path, line, column))

    return matching_refs


def get_short_name_at_position(
    doc_source: str, line: int
) -> tuple[str, int, int] | None:
    """Extract SHORT-NAME value and its position from a line.

    Args:
        doc_source: The full document source
        line: Line number (0-indexed)

    Returns:
        Tuple of (short_name, start_col, end_col) or None if not a SHORT-NAME line
    """
    lines = doc_source.splitlines()
    if line >= len(lines):
        return None

    line_text = lines[line]

    # Pattern to match <SHORT-NAME>value</SHORT-NAME>
    pattern = r"<SHORT-NAME>([^<]+)</SHORT-NAME>"
    match = re.search(pattern, line_text)

    if match:
        short_name = match.group(1)
        start_col = match.start(1)  # Start of the name (not the tag)
        end_col = match.end(1)  # End of the name
        return (short_name, start_col, end_col)

    return None


def validate_references(root: etree._Element) -> list[tuple[str, int, int, str]]:
    """Validate all references in the ARXML document.

    Returns:
        List of tuples: (tag_name, line_number, column, error_message)
    """
    errors = []

    # Build the tree structure
    tree = build_arxml_tree(root)

    # Find all references
    references = find_all_reference_elements(root)

    # Validate each reference
    for elem, ref_path, line, column in references:
        tag_name = elem.tag.split("}")[-1]

        # Try to find the referenced node
        target_node = tree.find_by_path(ref_path)

        if target_node is None:
            errors.append(
                (
                    tag_name,
                    line,
                    column,
                    f"Invalid reference: '{ref_path}' does not exist",
                )
            )

    return errors


def parse_arxml(text: str) -> etree.XMLSyntaxError | None:
    try:
        etree.fromstring(text.encode("utf-8"))
        return None
    except etree.XMLSyntaxError as e:
        return e


# XML Schema validation
def validate_arxml_schema(
    xml_text: str, schema_path: str
) -> (
    etree.DocumentInvalid
    | etree.XMLSchemaParseError
    | etree.XMLSyntaxError
    | Exception
    | None
):
    try:
        xml_doc = etree.fromstring(xml_text.encode("utf-8"))
        with open(schema_path, "rb") as f:
            schema_doc = etree.parse(f)
        schema = etree.XMLSchema(schema_doc)
        schema.assertValid(xml_doc)
        return None
    except (
        etree.DocumentInvalid,
        etree.XMLSchemaParseError,
        etree.XMLSyntaxError,
    ) as e:
        return e
    except Exception as e:
        return e


# @server.feature("textDocument/didOpen")
# @server.feature("textDocument/didChange")
# def validate_arxml(ls, params):
#     text_doc = ls.workspace.get_text_document(params.text_document.uri)
#     error = parse_arxml(text_doc.source)
#
#     diagnostics = []
#
#     if error is not None and error.lineno is not None:
#         diagnostics.append(
#             Diagnostic(
#                 range=Range(
#                     start=Position(
#                         line=error.lineno - 1,
#                         character=max(error.position[1] - 1, 0),
#                     ),
#                     end=Position(
#                         line=error.lineno - 1,
#                         character=max(error.position[1], 0),
#                     ),
#                 ),
#                 message=error.msg,
#                 severity=DiagnosticSeverity.Error,
#                 source="arxml-ls",
#             )
#         )
#
#     ls.publish_diagnostics(text_doc.uri, diagnostics)


# @server.feature("textDocument/didOpen")
# @server.feature("textDocument/didChange")
@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def validate_arxml(
    ls: LanguageServer,
    params: types.DidOpenTextDocumentParams | types.DidChangeTextDocumentParams,
) -> None:
    doc = ls.workspace.get_text_document(params.text_document.uri)
    diagnostics = []

    # First: standard XML syntax check
    error = parse_arxml(doc.source)
    if error and hasattr(error, "lineno") and error.lineno is not None:
        diagnostics.append(
            Diagnostic(
                range=Range(
                    start=Position(error.lineno - 1, 0),
                    end=Position(error.lineno - 1, 1),
                ),
                message=error.msg,
                severity=DiagnosticSeverity.Error,
                source="arxml-ls",
            )
        )
    else:
        # Second: XML Schema validation (if schema is available)
        schema_path = "/home/yura/autosar_20_11_schema/AUTOSAR_00049_COMPACT.xsd"
        schema_error = validate_arxml_schema(doc.source, schema_path)
        if schema_error and hasattr(schema_error, "error_log"):
            error_log = getattr(schema_error, "error_log", None)
            try:
                iterable_log = cast(Iterable[Any], error_log) if error_log else []
                for entry in iterable_log:
                    diagnostics.append(
                        Diagnostic(
                            range=Range(
                                start=Position(
                                    entry.line - 1, max(entry.column - 1, 0)
                                ),
                                end=Position(entry.line - 1, max(entry.column, 1)),
                            ),
                            message=f"Schema validation: {entry.message}",
                            severity=DiagnosticSeverity.Error,
                            source="arxml-ls",
                        )
                    )
            except Exception:
                pass
        elif schema_error:
            diagnostics.append(
                Diagnostic(
                    range=Range(
                        start=Position(0, 0),
                        end=Position(0, 1),
                    ),
                    message=f"Schema validation: {str(schema_error)}",
                    severity=DiagnosticSeverity.Error,
                    source="arxml-ls",
                )
            )

    # Third: Reference validation across workspace
    project_index = _get_project_index(ls, doc.uri)
    references = project_index.references_by_doc.get(doc.uri, [])
    project_doc = project_index.documents.get(doc.uri)
    doc_lines = project_doc.lines if project_doc else doc.source.splitlines()

    for elem, ref_path, line, column in references:
        if project_index.path_exists(ref_path):
            continue

        tag_name = elem.tag.split("}")[-1]
        start_line = max(line - 1, 0) if line else 0
        start_col = 0
        end_col = 1

        if line > 0 and line <= len(doc_lines):
            line_text = doc_lines[line - 1]
            span = locate_reference_span(line_text, ref_path)
            if span:
                start_col, end_col = span
            else:
                end_col = len(line_text)

        diagnostics.append(
            Diagnostic(
                range=Range(
                    start=Position(start_line, start_col),
                    end=Position(start_line, end_col),
                ),
                message=f"Invalid reference in {tag_name}: '{ref_path}' does not exist",
                severity=DiagnosticSeverity.Error,
                source="arxml-ls",
            )
        )

    ls.publish_diagnostics(doc.uri, diagnostics)


@server.feature("textDocument/hover")
def hover(ls: LanguageServer, params: types.HoverParams) -> Hover | None:
    doc = ls.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.splitlines()

    if params.position.line >= len(lines):
        return None

    line = lines[params.position.line].strip()

    if line.startswith("<") and not line.startswith("</"):
        tag = line.split()[0].replace("<", "").replace(">", "")
        return Hover(
            contents=MarkupContent(
                kind=MarkupKind.Markdown, value=f"**AUTOSAR element:** `{tag}`"
            )
        )

    return None


@server.feature("textDocument/documentSymbol")
def document_symbols(
    ls: LanguageServer, params: types.DocumentSymbolParams
) -> list[SymbolInformation]:
    """Provide document symbols for AUTOSAR XML elements.

    Args:"""
    doc = ls.workspace.get_document(params.text_document.uri)
    symbols = []

    try:
        root = etree.fromstring(doc.source.encode("utf-8"))
    except Exception:
        return symbols

    for elem in root.iter():
        if elem.sourceline:
            symbols.append(
                SymbolInformation(
                    name=elem.tag.split("}")[-1],
                    kind=SymbolKind.Class,
                    location=Location(
                        uri=doc.uri,
                        range=Range(
                            start=Position(elem.sourceline - 1, 0),
                            end=Position(elem.sourceline - 1, 0),
                        ),
                    ),
                )
            )
    return symbols


@server.feature("textDocument/definition")
def go_to_definition(
    ls: LanguageServer, params: TextDocumentPositionParams
) -> Location | None:
    """Jump to the definition of a referenced element in ARXML.

    When the cursor is on a path segment within a -REF or -TREF tag,
    this will jump to the element corresponding to that specific segment.

    If the cursor is not on a path segment (e.g., on the tag name or attributes),
    it will fall back to jumping to the full path specified in the reference.

    Example:
        Path: /Application/Components/MyComponent
        Cursor on "Components" -> jumps to Components element
        Cursor on "MyComponent" -> jumps to MyComponent element
        Cursor on "TREF" tag name -> jumps to MyComponent element (full path)
    """
    doc = ls.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.splitlines()

    if params.position.line >= len(lines):
        return None

    line = lines[params.position.line]

    # Step 1: Try to get the path segment at cursor position (precise navigation)
    segment_info = get_path_segment_at_cursor(line, params.position.character)

    # If cursor is on a specific segment, use that
    if segment_info:
        target_path, segment_idx = segment_info
    else:
        # Fallback: cursor not on path segment, use full path from the line
        full_path = extract_reference_from_line(line)
        if not full_path:
            return None
        target_path = full_path

    # Step 2: Parse XML and build tree
    project_index = _get_project_index(ls, doc.uri)
    target_entry = project_index.find_node(target_path)
    if not target_entry:
        return None
    target_uri, target_node = target_entry

    # Step 4: Return location of the target element
    if (
        not hasattr(target_node.element, "sourceline")
        or target_node.element.sourceline is None
    ):
        return None

    target_line = target_node.element.sourceline
    return Location(
        uri=target_uri,
        range=Range(
            start=Position(target_line - 1, 0),
            end=Position(target_line - 1, 100),  # Highlight whole line
        ),
    )


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
def find_references(
    ls: LanguageServer, params: types.ReferenceParams
) -> list[Location] | None:
    """Find all references to a SHORT-NAME element.

    When the cursor is on a SHORT-NAME line, this finds all -REF and -TREF
    tags that reference this element's path.

    Args:
        ls: Language server instance
        params: Reference request parameters with position and context

    Returns:
        List of locations where this element is referenced, or None
    """
    doc = ls.workspace.get_text_document(params.text_document.uri)

    # Step 1: Check if cursor is on a SHORT-NAME line
    short_name_info = get_short_name_at_position(doc.source, params.position.line)

    if not short_name_info:
        return None

    project_index = _get_project_index(ls, doc.uri)
    project_doc = project_index.documents.get(doc.uri)
    if not project_doc or not project_doc.tree:
        return None

    target_node = find_node_by_short_name_line(project_doc.tree, params.position.line)

    if not target_node:
        return None

    target_path = target_node.path

    # Step 4: Find all references to this path and child paths
    locations = []

    for ref_doc_uri, ref_entries in project_index.references_by_doc.items():
        ref_doc = project_index.documents.get(ref_doc_uri)
        if not ref_doc:
            continue
        lines = ref_doc.lines
        for elem, ref_path, line, col in ref_entries:
            is_exact = ref_path == target_path
            is_child = ref_path.startswith(f"{target_path}/")
            if not (is_exact or is_child):
                continue
            if line <= 0 or line > len(lines):
                continue
            line_text = lines[line - 1]
            span = locate_reference_span(line_text, ref_path)
            if not span:
                span = (0, len(line_text))
            ref_start, ref_end = span
            locations.append(
                Location(
                    uri=ref_doc_uri,
                    range=Range(
                        start=Position(line - 1, ref_start),
                        end=Position(line - 1, ref_end),
                    ),
                )
            )

    # Step 5: Optionally include the definition itself if requested
    if params.context.include_declaration:
        # Add the SHORT-NAME line itself
        short_name, start_col, end_col = short_name_info
        locations.append(
            Location(
                uri=doc.uri,
                range=Range(
                    start=Position(params.position.line, start_col),
                    end=Position(params.position.line, end_col),
                ),
            )
        )

    return locations if locations else None


@server.feature(types.TEXT_DOCUMENT_PREPARE_RENAME)
def prepare_rename(
    ls: LanguageServer, params: types.PrepareRenameParams
) -> PrepareRenameResult | Range | None:
    """Prepare rename - validates that renaming is possible at the cursor position.

    This is called before the actual rename to check if the position is renameable.
    For ARXML, we allow renaming SHORT-NAME elements.
    """
    doc = ls.workspace.get_text_document(params.text_document.uri)

    # Check if cursor is on a SHORT-NAME line
    short_name_info = get_short_name_at_position(doc.source, params.position.line)

    if short_name_info:
        short_name, start_col, end_col = short_name_info
        # Return the range of the SHORT-NAME value (not the tags)
        return Range(
            start=Position(params.position.line, start_col),
            end=Position(params.position.line, end_col),
        )

    return None


@server.feature(types.TEXT_DOCUMENT_RENAME)
def rename(ls: LanguageServer, params: types.RenameParams) -> WorkspaceEdit | None:
    """Rename a SHORT-NAME and update all references to it.

    When renaming a SHORT-NAME element, this will:
    1. Update the SHORT-NAME itself
    2. Find all references pointing to this element's path
    3. Update those references with the new name
    4. Handle child paths if they exist
    """
    doc = ls.workspace.get_text_document(params.text_document.uri)
    new_name = params.new_name

    # Step 1: Check if cursor is on a SHORT-NAME line
    short_name_info = get_short_name_at_position(doc.source, params.position.line)
    if not short_name_info:
        return None

    old_name, start_col, end_col = short_name_info

    project_index = _get_project_index(ls, doc.uri)
    project_doc = project_index.documents.get(doc.uri)
    if not project_doc or not project_doc.tree:
        return None

    target_node = find_node_by_short_name_line(project_doc.tree, params.position.line)

    if not target_node:
        return None

    old_path = target_node.path

    # Step 4: Calculate the new path
    path_parts = old_path.rsplit("/", 1)
    if len(path_parts) == 2:
        parent_path, _ = path_parts
        new_path = f"{parent_path}/{new_name}"
    else:
        new_path = f"/{new_name}"

    # Step 5: Find all references that need to be updated
    changes: Dict[str, List[TextEdit]] = {}

    def add_edit(uri: str, edit: TextEdit) -> None:
        changes.setdefault(uri, []).append(edit)

    # 5a. Update the SHORT-NAME itself
    add_edit(
        doc.uri,
        TextEdit(
            range=Range(
                start=Position(params.position.line, start_col),
                end=Position(params.position.line, end_col),
            ),
            new_text=new_name,
        ),
    )

    # 5b. Update references across all documents
    for ref_doc_uri, ref_entries in project_index.references_by_doc.items():
        ref_doc = project_index.documents.get(ref_doc_uri)
        if not ref_doc:
            continue
        lines = ref_doc.lines
        for elem, ref_path, line, col in ref_entries:
            replacement: str | None = None
            if ref_path == old_path:
                replacement = new_path
            elif ref_path.startswith(f"{old_path}/"):
                replacement = new_path + ref_path[len(old_path) :]

            if replacement is None:
                continue

            if line <= 0 or line > len(lines):
                continue

            line_text = lines[line - 1]
            span = locate_reference_span(line_text, ref_path)
            if not span:
                span = (0, len(line_text))
            ref_start, ref_end = span

            add_edit(
                ref_doc_uri,
                TextEdit(
                    range=Range(
                        start=Position(line - 1, ref_start),
                        end=Position(line - 1, ref_end),
                    ),
                    new_text=replacement,
                ),
            )

    # Step 6: Return the workspace edit with all changes
    return WorkspaceEdit(changes=changes)


if __name__ == "__main__":
    server.start_io()
