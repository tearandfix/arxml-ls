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
)
from lsprotocol import types

from lxml import etree
from dataclasses import dataclass, field


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


def find_references(root: etree._Element) -> list[tuple[etree._Element, str, int, int]]:
    """Find all reference elements (-REF or -TREF) and their paths.

    Returns:
        List of tuples: (element, reference_path, line_number, column)
    """
    references = []

    for elem in root.iter():
        tag_name = elem.tag.split("}")[-1]  # Remove namespace
        if tag_name.endswith("REF") or tag_name.endswith("TREF"):
            if elem.text:
                ref_path = elem.text.strip()
                line = elem.sourceline if hasattr(elem, "sourceline") else 0
                column = 0  # lxml doesn't provide column info easily
                references.append((elem, ref_path, line, column))

    return references


def validate_references(root: etree._Element) -> list[tuple[str, int, int, str]]:
    """Validate all references in the ARXML document.

    Returns:
        List of tuples: (tag_name, line_number, column, error_message)
    """
    errors = []

    # Build the tree structure
    tree = build_arxml_tree(root)

    # Find all references
    references = find_references(root)

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
            error_log = schema_error.error_log  # type: ignore
            try:
                for entry in error_log:
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

    # Third: Reference validation
    try:
        root = etree.fromstring(doc.source.encode("utf-8"))
        ref_errors = validate_references(root)

        for tag_name, line, column, error_msg in ref_errors:
            diagnostics.append(
                Diagnostic(
                    range=Range(
                        start=Position(line - 1, column),
                        end=Position(line - 1, column + 100),  # approximate end
                    ),
                    message=error_msg,
                    severity=DiagnosticSeverity.Error,
                    source="arxml-ls",
                )
            )
    except Exception:
        # ignore parsing errors here; they are already reported above
        pass

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
    doc = ls.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.splitlines()

    if params.position.line >= len(lines):
        return None

    return Location(
        uri=doc.uri,
        range=Range(start=Position(1, 0), end=Position(0, 0)),
    )
    # # Get current word under cursor (naive)
    # line = lines[params.position.line]
    # word = line.strip().strip("<>").split(">")[0]  # crude, just for demo
    #
    # # Only handle *-REF tags
    # if not word.endswith("-REF"):
    #     return None
    #
    # # Parse XML
    # try:
    #     root = etree.fromstring(doc.source.encode("utf-8"))
    # except Exception:
    #     return None
    #
    # # Find the referenced target
    # ref_value = line.split(">")[1].split("<")[0].strip()  # value inside <*-REF>
    # if not ref_value:
    #     return None
    #
    # # Search for element with UUID or ID matching ref_value
    # for elem in root.iter():
    #     elem_id = elem.get("UUID") or elem.get("ID")
    #     if elem_id == ref_value:
    #         # Return its location
    #         return Location(
    #             uri=doc.uri,
    #             range=Range(
    #                 start=Position(elem.sourceline - 1, 0),
    #                 end=Position(elem.sourceline - 1, 100),
    #             ),
    #         )
    #
    # return None


if __name__ == "__main__":
    server.start_io()
