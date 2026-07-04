"""Tests for shared.frontmatter_io.FrontmatterIO."""

import sys
import pytest
from pathlib import Path
from unittest.mock import patch

from shared.frontmatter_io import FrontmatterIO, _load_yaml, _dump_yaml


@pytest.fixture
def fmio():
    return FrontmatterIO()


class TestFrontmatterIORead:
    def test_reads_frontmatter_and_body(self, fmio, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("---\nid: npc-test\ntype: npc\n---\nBody text here.\n", encoding="utf-8")
        fm, body = fmio.read(f)
        assert fm["id"] == "npc-test"
        assert fm["type"] == "npc"
        assert "Body text here." in body

    def test_returns_empty_dict_when_no_frontmatter(self, fmio, tmp_path):
        f = tmp_path / "plain.md"
        f.write_text("Just a plain markdown file.\n", encoding="utf-8")
        fm, body = fmio.read(f)
        assert fm == {}
        assert "plain markdown" in body

    def test_body_empty_after_frontmatter_only(self, fmio, tmp_path):
        f = tmp_path / "fm_only.md"
        f.write_text("---\nkey: val\n---\n", encoding="utf-8")
        fm, body = fmio.read(f)
        assert fm["key"] == "val"
        assert body == ""

    def test_list_value_in_frontmatter(self, fmio, tmp_path):
        f = tmp_path / "list.md"
        f.write_text("---\ntags:\n  - undead\n  - villain\n---\n", encoding="utf-8")
        fm, _ = fmio.read(f)
        assert "undead" in fm["tags"]
        assert "villain" in fm["tags"]

    def test_multiline_body_preserved(self, fmio, tmp_path):
        body_text = "Line 1\nLine 2\nLine 3\n"
        f = tmp_path / "multi.md"
        f.write_text(f"---\nid: x\n---\n{body_text}", encoding="utf-8")
        _, body = fmio.read(f)
        assert body == body_text

    def test_nested_frontmatter(self, fmio, tmp_path):
        f = tmp_path / "nested.md"
        f.write_text("---\nid: x\nrelationships:\n  - '[[npc-a]]'\n---\n", encoding="utf-8")
        fm, _ = fmio.read(f)
        assert "[[npc-a]]" in fm["relationships"]

    def test_boolean_and_int_types(self, fmio, tmp_path):
        f = tmp_path / "types.md"
        f.write_text("---\nreviewed: false\nquality: 7\n---\n", encoding="utf-8")
        fm, _ = fmio.read(f)
        assert fm["reviewed"] is False
        assert fm["quality"] == 7

    def test_crlf_frontmatter(self, fmio, tmp_path):
        f = tmp_path / "crlf.md"
        f.write_bytes(b"---\r\nid: crlf\r\n---\r\nBody\r\n")
        fm, body = fmio.read(f)
        assert fm["id"] == "crlf"

    def test_frontmatter_fence_with_trailing_spaces(self, fmio, tmp_path):
        f = tmp_path / "spaces.md"
        f.write_text("---   \nid: spaced\n---   \nBody\n", encoding="utf-8")
        fm, body = fmio.read(f)
        assert fm.get("id") == "spaced"


class TestFrontmatterIOWrite:
    def test_write_creates_file(self, fmio, tmp_path):
        path = tmp_path / "out.md"
        fmio.write(path, {"id": "npc-x", "type": "npc"}, "## Description\n")
        assert path.exists()

    def test_write_round_trip(self, fmio, tmp_path):
        path = tmp_path / "roundtrip.md"
        original_fm = {"id": "loc-x", "type": "location", "quality": 8}
        original_body = "## Details\nSome text.\n"
        fmio.write(path, original_fm, original_body)
        fm, body = fmio.read(path)
        assert fm["id"] == "loc-x"
        assert fm["quality"] == 8
        assert "Some text." in body

    def test_write_starts_with_fence(self, fmio, tmp_path):
        path = tmp_path / "fence.md"
        fmio.write(path, {"k": "v"}, "body")
        content = path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "\n---\n" in content

    def test_write_creates_parent_dirs(self, fmio, tmp_path):
        path = tmp_path / "sub" / "deep" / "file.md"
        fmio.write(path, {"x": 1}, "")
        assert path.exists()

    def test_write_list_values(self, fmio, tmp_path):
        path = tmp_path / "list.md"
        fmio.write(path, {"tags": ["undead", "boss"]}, "")
        fm, _ = fmio.read(path)
        assert "undead" in fm["tags"]

    def test_write_bool_false_preserved(self, fmio, tmp_path):
        path = tmp_path / "bool.md"
        fmio.write(path, {"reviewed": False}, "")
        fm, _ = fmio.read(path)
        assert fm["reviewed"] is False

    def test_write_utf8_encoding(self, fmio, tmp_path):
        path = tmp_path / "unicode.md"
        fmio.write(path, {"name": "Ñoño"}, "Ñoño body")
        content = path.read_bytes()
        assert "Ñoño".encode("utf-8") in content

    def test_write_overwrites_existing(self, fmio, tmp_path):
        path = tmp_path / "overwrite.md"
        fmio.write(path, {"v": 1}, "old")
        fmio.write(path, {"v": 2}, "new")
        fm, body = fmio.read(path)
        assert fm["v"] == 2
        assert "new" in body


# ---------------------------------------------------------------------------
# PyYAML fallback paths (ruamel.yaml unavailable)
# ---------------------------------------------------------------------------

class TestFrontmatterIOPyYAMLFallback:
    """Exercise the except ImportError branches by masking ruamel.yaml."""

    def _without_ruamel(self):
        """Context: make 'from ruamel.yaml import YAML' raise ImportError."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name in ("ruamel.yaml", "ruamel"):
                raise ImportError("ruamel.yaml not available")
            return real_import(name, *args, **kwargs)

        return patch("builtins.__import__", side_effect=mock_import)

    def test_load_yaml_fallback_parses(self):
        with self._without_ruamel():
            result = _load_yaml("id: test\ntype: npc\n")
        assert result["id"] == "test"

    def test_load_yaml_fallback_empty(self):
        with self._without_ruamel():
            result = _load_yaml("")
        assert result == {}

    def test_dump_yaml_fallback_produces_string(self):
        with self._without_ruamel():
            result = _dump_yaml({"id": "test", "type": "npc"})
        assert "id" in result
        assert "test" in result

    def test_dump_yaml_fallback_unicode(self):
        with self._without_ruamel():
            result = _dump_yaml({"name": "Ñoño"})
        assert "Ñoño" in result

    def test_round_trip_via_fallback(self, tmp_path):
        fmio = FrontmatterIO()
        path = tmp_path / "fallback.md"
        with self._without_ruamel():
            fmio.write(path, {"id": "x", "quality": 5}, "body text\n")
            fm, body = fmio.read(path)
        assert fm["id"] == "x"
        assert fm["quality"] == 5
        assert "body text" in body
