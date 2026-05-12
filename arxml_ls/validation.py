import os

from lxml import etree

from .schema import get_schema_path


def _resolve_schema_path() -> str:
    env = os.environ.get("ARXML_SCHEMA_PATH")
    if env:
        return env
    try:
        return str(get_schema_path())
    except Exception:
        return ""


SCHEMA_PATH = _resolve_schema_path()


def parse_arxml(text: str) -> etree.XMLSyntaxError | None:
    try:
        etree.fromstring(text.encode("utf-8"))
        return None
    except etree.XMLSyntaxError as e:
        return e


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
