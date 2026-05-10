import os

from lxml import etree


SCHEMA_PATH = os.environ.get(
    "ARXML_SCHEMA_PATH",
    "/home/yura/autosar_20_11_schema/AUTOSAR_00049_COMPACT.xsd",
)


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
