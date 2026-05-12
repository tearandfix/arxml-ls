import io
import os
import urllib.request
import zipfile
from pathlib import Path

_SCHEMA_FILENAME = "AUTOSAR_00049_COMPACT.xsd"
_SCHEMA_URL = "https://www.autosar.org/fileadmin/standards/R20-11/FO/AUTOSAR_TR_XMLSchemaSupplement.zip"


def _cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "arxml-ls"


def get_schema_path() -> Path:
    """Return path to AUTOSAR_00049_COMPACT.xsd, downloading it on first call."""
    dest = _cache_dir() / _SCHEMA_FILENAME
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(_SCHEMA_URL) as response:
        data = response.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        content = zf.read(_SCHEMA_FILENAME)
    dest.write_bytes(content)
    return dest
