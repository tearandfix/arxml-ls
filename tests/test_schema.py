import io
import zipfile
from unittest.mock import MagicMock, patch

from arxml_ls.schema import get_schema_path


def _make_zip(filename: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(filename, content)
    return buf.getvalue()


FAKE_XSD = b"<xs:schema/>"
FAKE_ZIP = _make_zip("AUTOSAR_00049_COMPACT.xsd", FAKE_XSD)


class TestGetSchemaPath:
    def test_returns_cached_file_without_downloading(self, tmp_path):
        existing = tmp_path / "AUTOSAR_00049_COMPACT.xsd"
        existing.write_bytes(FAKE_XSD)

        with patch("arxml_ls.schema._cache_dir", return_value=tmp_path), \
             patch("urllib.request.urlopen") as mock_urlopen:
            result = get_schema_path()

        mock_urlopen.assert_not_called()
        assert result == existing

    def test_downloads_and_extracts_when_missing(self, tmp_path):
        response = MagicMock()
        response.read.return_value = FAKE_ZIP
        response.__enter__ = lambda s: s
        response.__exit__ = MagicMock(return_value=False)

        with patch("arxml_ls.schema._cache_dir", return_value=tmp_path), \
             patch("urllib.request.urlopen", return_value=response):
            result = get_schema_path()

        assert result == tmp_path / "AUTOSAR_00049_COMPACT.xsd"
        assert result.read_bytes() == FAKE_XSD

    def test_creates_cache_dir_if_missing(self, tmp_path):
        cache = tmp_path / "nested" / "arxml-ls"
        response = MagicMock()
        response.read.return_value = FAKE_ZIP
        response.__enter__ = lambda s: s
        response.__exit__ = MagicMock(return_value=False)

        with patch("arxml_ls.schema._cache_dir", return_value=cache), \
             patch("urllib.request.urlopen", return_value=response):
            result = get_schema_path()

        assert cache.is_dir()
        assert result.exists()
