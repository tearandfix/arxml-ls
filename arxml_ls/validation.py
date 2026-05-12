import logging
import os

from lxml import etree

from .schema import get_schema_path

logger = logging.getLogger("arxml-ls")


def _resolve_schema_path() -> str:
    env = os.environ.get("ARXML_SCHEMA_PATH")
    if env:
        logger.info("schema path from ARXML_SCHEMA_PATH env: %s", env)
        return env
    try:
        path = str(get_schema_path())
        logger.info("schema path from get_schema_path: %s", path)
        return path
    except Exception as e:
        logger.warning("schema path resolution failed: %s", e)
        return ""


SCHEMA_PATH = _resolve_schema_path()
logger.info("SCHEMA_PATH resolved to: %r", SCHEMA_PATH)


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
    if not schema_path:
        logger.debug("schema validation skipped: no schema file")
        return None
    logger.debug("validating against schema: %s", schema_path)
    try:
        xml_doc = etree.fromstring(xml_text.encode("utf-8"))
        with open(schema_path, "rb") as f:
            schema_doc = etree.parse(f)
        schema = etree.XMLSchema(schema_doc)
        schema.assertValid(xml_doc)
        logger.debug("schema validation passed")
        return None
    except (
        etree.DocumentInvalid,
        etree.XMLSchemaParseError,
        etree.XMLSyntaxError,
    ) as e:
        logger.debug("schema validation error: %s", e)
        return e
    except Exception as e:
        logger.warning("schema validation unexpected error: %s", e)
        return e
