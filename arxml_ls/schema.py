import io
import logging
import os
import urllib.request
import zipfile
from pathlib import Path

_SCHEMA_FILENAME = "AUTOSAR_00049_COMPACT.xsd"
_SCHEMA_URL = "https://www.autosar.org/fileadmin/standards/R20-11/FO/AUTOSAR_TR_XMLSchemaSupplement.zip"
_XML_XSD_FILENAME = "xml.xsd"
_XML_XSD_URL = "http://www.w3.org/2001/xml.xsd"

logger = logging.getLogger("arxml-ls")


def _cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "arxml-ls"


def _ensure_xml_xsd(cache: Path) -> None:
    dest = cache / _XML_XSD_FILENAME
    if dest.exists():
        logger.debug("xml.xsd already cached at %s", dest)
        return
    logger.info("downloading xml.xsd from %s", _XML_XSD_URL)
    try:
        with urllib.request.urlopen(_XML_XSD_URL) as response:
            data = response.read()
        dest.write_bytes(data)
        logger.info("xml.xsd downloaded (%d bytes) to %s", len(data), dest)
    except Exception as e:
        logger.error("failed to download xml.xsd: %s", e)
        raise


def get_schema_path() -> Path:
    """Return path to AUTOSAR_00049_COMPACT.xsd, downloading it and xml.xsd on first call."""
    cache = _cache_dir()
    logger.debug("schema cache dir: %s", cache)
    dest = cache / _SCHEMA_FILENAME
    if dest.exists():
        logger.debug("AUTOSAR schema already cached at %s", dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        logger.info("downloading AUTOSAR schema zip from %s", _SCHEMA_URL)
        try:
            with urllib.request.urlopen(_SCHEMA_URL) as response:
                data = response.read()
            logger.debug("zip downloaded (%d bytes), extracting %s", len(data), _SCHEMA_FILENAME)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                content = zf.read(_SCHEMA_FILENAME)
            dest.write_bytes(content)
            logger.info("AUTOSAR schema extracted (%d bytes) to %s", len(content), dest)
        except Exception as e:
            logger.error("failed to download/extract AUTOSAR schema: %s", e)
            raise
    _ensure_xml_xsd(cache)
    return dest
