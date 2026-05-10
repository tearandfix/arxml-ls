from typing import Any, Dict, Iterable, List, cast

from lsprotocol import types
from lsprotocol.types import (
    Diagnostic,
    DiagnosticSeverity,
    Hover,
    Location,
    MarkupContent,
    MarkupKind,
    Position,
    PrepareRenameResult,
    Range,
    SymbolInformation,
    SymbolKind,
    TextDocumentPositionParams,
    TextEdit,
    WorkspaceEdit,
)
from lxml import etree
from pygls.lsp.server import LanguageServer

from .analysis import (
    extract_reference_from_line,
    find_node_by_short_name_line,
    get_path_segment_at_cursor,
    get_short_name_at_position,
    locate_reference_span,
)
from .indexing import _get_project_index
from .validation import SCHEMA_PATH, parse_arxml, validate_arxml_schema


class ArxmlLanguageServer(LanguageServer):
    CMD_NAME = "arxml-ls"


server = ArxmlLanguageServer("arxml-ls", "0.1.0")


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def validate_arxml(
    ls: LanguageServer,
    params: types.DidOpenTextDocumentParams | types.DidChangeTextDocumentParams,
) -> None:
    doc = ls.workspace.get_text_document(params.text_document.uri)
    diagnostics = []

    # Pass 1: XML syntax
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
        # Pass 2: XSD schema (skipped silently if schema file is absent)
        schema_error = validate_arxml_schema(doc.source, SCHEMA_PATH)
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
                    range=Range(start=Position(0, 0), end=Position(0, 1)),
                    message=f"Schema validation: {schema_error}",
                    severity=DiagnosticSeverity.Error,
                    source="arxml-ls",
                )
            )

    # Pass 3: Cross-workspace reference validity
    project_index = _get_project_index(ls, doc.uri)
    references = project_index.references_by_doc.get(doc.uri, [])
    project_doc = project_index.documents.get(doc.uri)
    doc_lines = project_doc.lines if project_doc else doc.source.splitlines()

    for elem, ref_path, line, _col in references:
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

    ls.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=doc.uri, diagnostics=diagnostics)
    )


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
    doc = ls.workspace.get_text_document(params.text_document.uri)
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
    """Jump to the element under the cursor.

    When the cursor is on a path segment within a -REF or -TREF tag, this jumps
    to the element for that specific segment rather than the leaf of the full path.
    Falls back to the full path when the cursor is on the tag name or attributes.
    """
    doc = ls.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.splitlines()

    if params.position.line >= len(lines):
        return None

    line = lines[params.position.line]

    # Step 1: Try segment-aware navigation first
    segment_info = get_path_segment_at_cursor(line, params.position.character)
    if segment_info:
        target_path, _segment_idx = segment_info
    else:
        # Step 2: Fall back to the full reference path on this line
        target_path = extract_reference_from_line(line)
        if not target_path:
            return None

    # Step 3: Look up target in the project index
    project_index = _get_project_index(ls, doc.uri)
    target_entry = project_index.find_node(target_path)
    if not target_entry:
        return None
    target_uri, target_node = target_entry

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
            end=Position(target_line - 1, 100),
        ),
    )


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
def find_references(
    ls: LanguageServer, params: types.ReferenceParams
) -> list[Location] | None:
    """Find all -REF/-TREF elements across the workspace that point to the SHORT-NAME under cursor."""
    doc = ls.workspace.get_text_document(params.text_document.uri)

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
    locations = []

    for ref_doc_uri, ref_entries in project_index.references_by_doc.items():
        ref_doc = project_index.documents.get(ref_doc_uri)
        if not ref_doc:
            continue
        lines = ref_doc.lines
        for elem, ref_path, line, _col in ref_entries:
            if ref_path != target_path and not ref_path.startswith(f"{target_path}/"):
                continue
            if line <= 0 or line > len(lines):
                continue
            line_text = lines[line - 1]
            span = locate_reference_span(line_text, ref_path) or (0, len(line_text))
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

    if params.context.include_declaration:
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
    """Validate that the cursor is on a renameable SHORT-NAME."""
    doc = ls.workspace.get_text_document(params.text_document.uri)
    short_name_info = get_short_name_at_position(doc.source, params.position.line)
    if short_name_info:
        _short_name, start_col, end_col = short_name_info
        return Range(
            start=Position(params.position.line, start_col),
            end=Position(params.position.line, end_col),
        )
    return None


@server.feature(types.TEXT_DOCUMENT_RENAME)
def rename(ls: LanguageServer, params: types.RenameParams) -> WorkspaceEdit | None:
    """Rename a SHORT-NAME and update all references to it across the workspace."""
    doc = ls.workspace.get_text_document(params.text_document.uri)
    new_name = params.new_name

    short_name_info = get_short_name_at_position(doc.source, params.position.line)
    if not short_name_info:
        return None

    _old_name, start_col, end_col = short_name_info

    project_index = _get_project_index(ls, doc.uri)
    project_doc = project_index.documents.get(doc.uri)
    if not project_doc or not project_doc.tree:
        return None

    target_node = find_node_by_short_name_line(project_doc.tree, params.position.line)
    if not target_node:
        return None

    old_path = target_node.path
    path_parts = old_path.rsplit("/", 1)
    new_path = f"{path_parts[0]}/{new_name}" if len(path_parts) == 2 else f"/{new_name}"

    changes: Dict[str, List[TextEdit]] = {}

    def add_edit(uri: str, edit: TextEdit) -> None:
        changes.setdefault(uri, []).append(edit)

    # Update the SHORT-NAME itself
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

    # Update all references across the workspace
    for ref_doc_uri, ref_entries in project_index.references_by_doc.items():
        ref_doc = project_index.documents.get(ref_doc_uri)
        if not ref_doc:
            continue
        lines = ref_doc.lines
        for elem, ref_path, line, _col in ref_entries:
            if ref_path == old_path:
                replacement = new_path
            elif ref_path.startswith(f"{old_path}/"):
                replacement = new_path + ref_path[len(old_path) :]
            else:
                continue

            if line <= 0 or line > len(lines):
                continue

            line_text = lines[line - 1]
            span = locate_reference_span(line_text, ref_path) or (0, len(line_text))
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

    return WorkspaceEdit(changes=changes)
