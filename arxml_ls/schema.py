import io
import os
import urllib.request
import zipfile
from pathlib import Path

_SCHEMA_FILENAME = "AUTOSAR_00049_COMPACT.xsd"
_SCHEMA_URL = "https://www.autosar.org/fileadmin/standards/R20-11/FO/AUTOSAR_TR_XMLSchemaSupplement.zip"
_XML_XSD_FILENAME = "xml.xsd"
_XML_XSD_URL = "http://www.w3.org/2001/xml.xsd"


def _cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "arxml-ls"


def _ensure_xml_xsd(cache: Path) -> None:
    dest = cache / _XML_XSD_FILENAME
    if dest.exists():
        return
    with urllib.request.urlopen(_XML_XSD_URL) as response:
        dest.write_bytes(response.read())


def get_schema_path() -> Path:
    """Return path to AUTOSAR_00049_COMPACT.xsd, downloading it and xml.xsd on first call."""
    cache = _cache_dir()
    dest = cache / _SCHEMA_FILENAME
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(_SCHEMA_URL) as response:
            data = response.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            content = zf.read(_SCHEMA_FILENAME)
        dest.write_bytes(content)
    _ensure_xml_xsd(cache)
    return dest
