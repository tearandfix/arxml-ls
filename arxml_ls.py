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
    TextDocumentPositionParams
)
from lsprotocol import types

from lxml import etree

class ArxmlLanguageServer(LanguageServer):
    CMD_NAME = "arxml-ls"

server = ArxmlLanguageServer("arxml-ls", "0.1.0")

def parse_arxml(text: str) -> Exception | None:
    try:
        etree.fromstring(text.encode("utf-8"))
        return None
    except etree.XMLSyntaxError as e:
        return 

# XML Schema validation
def validate_arxml_schema(xml_text: str, schema_path: str) -> Exception | None:
    try:
        xml_doc = etree.fromstring(xml_text.encode("utf-8"))
        with open(schema_path, "rb") as f:
            schema_doc = etree.parse(f)
        schema = etree.XMLSchema(schema_doc)
        schema.assertValid(xml_doc)
        return None
    except (etree.DocumentInvalid, etree.XMLSchemaParseError, etree.XMLSyntaxError) as e:
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
def validate_arxml(ls: LanguageServer, params: types.DidOpenTextDocumentParams | types.DidChangeTextDocumentParams) -> None:
    doc = ls.workspace.get_text_document(params.text_document.uri)
    diagnostics = []

    # First: standard XML syntax check
    error = parse_arxml(doc.source)
    if error:
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
        schema_path = "/home/yura/autosar_20_11_schema/AUTOSAR_00049.xsd"
        schema_error = validate_arxml_schema(doc.source, schema_path)
        if schema_error and hasattr(schema_error, "error_log") and len(schema_error.error_log) > 0:
            for entry in schema_error.error_log:
                diagnostics.append(
                    Diagnostic(
                        range=Range(
                            start=Position(entry.line - 1, max(entry.column - 1, 0)),
                            end=Position(entry.line - 1, max(entry.column, 1)),
                        ),
                        message=f"Schema validation: {entry.message}",
                        severity=DiagnosticSeverity.Error,
                        source="arxml-ls",
                    )
                )
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

    # Third: REF tag diagnostics
    try:
        root = etree.fromstring(doc.source.encode("utf-8"))
        for elem in root.iter():
            tag_name = elem.tag.split("}")[-1]  # remove namespace if present
            if tag_name.endswith("REF"):
                # Report warning on this line
                diagnostics.append(
                    Diagnostic(
                        range=Range(
                            start=Position(elem.sourceline - 1, 0),
                            end=Position(elem.sourceline - 1, 100),  # approximate
                        ),
                        message=f"Reference element found: <{tag_name}>",
                        severity=DiagnosticSeverity.Warning,
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
                kind=MarkupKind.Markdown,
                value=f"**AUTOSAR element:** `{tag}`"
            )
        )

    return None

@server.feature("textDocument/documentSymbol")
def document_symbols(ls: LanguageServer, params: types.DocumentSymbolParams) -> list[SymbolInformation]:
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
def go_to_definition(ls: LanguageServer, params: TextDocumentPositionParams) -> Location | None:
    doc = ls.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.splitlines()
    
    if params.position.line >= len(lines):
        return None

    return Location(
        uri=doc.uri,
        range=Range(
            start=Position(1, 0),
            end=Position(0, 0)
        ),
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
