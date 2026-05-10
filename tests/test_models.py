from pathlib import Path

from lxml import etree

from arxml_ls.models import ArxmlNode, ProjectDocument, ProjectIndex


def _make_elem():
    return etree.fromstring("<elem/>")


def _make_node(name, path, children=None):
    return ArxmlNode(
        name=name, path=path, element=_make_elem(), children=children or {}
    )


def _make_virtual_root(children=None):
    """Virtual root as produced by build_arxml_tree: name="" path=""."""
    return ArxmlNode(name="", path="", element=_make_elem(), children=children or {})


class TestArxmlNodeFindByPath:
    # find_by_path is designed to be called on the virtual root (name="", path="")
    # that build_arxml_tree always produces.

    def test_finds_direct_child_by_absolute_path(self):
        child = _make_node("Child", "/Child")
        root = _make_virtual_root({"Child": child})
        assert root.find_by_path("/Child") is child

    def test_finds_nested_descendant(self):
        leaf = _make_node("Leaf", "/Mid/Leaf")
        mid = _make_node("Mid", "/Mid", children={"Leaf": leaf})
        root = _make_virtual_root({"Mid": mid})
        assert root.find_by_path("/Mid/Leaf") is leaf

    def test_returns_self_when_path_matches(self):
        node = _make_node("Node", "/Node")
        assert node.find_by_path("/Node") is node

    def test_returns_none_for_missing_path(self):
        root = _make_virtual_root()
        assert root.find_by_path("/Missing") is None

    def test_relative_path_traverses_from_current_node(self):
        child = _make_node("Child", "/Child")
        root = _make_virtual_root({"Child": child})
        # Without leading slash: path segments traversed from self.children directly
        assert root.find_by_path("Child") is child


class TestProjectDocumentLines:
    def test_splits_source_into_lines(self):
        doc = ProjectDocument(uri="u", path=Path("f"), source="a\nb\nc")
        assert doc.lines == ["a", "b", "c"]

    def test_single_line_source(self):
        doc = ProjectDocument(uri="u", path=Path("f"), source="only")
        assert doc.lines == ["only"]

    def test_lines_are_cached(self):
        doc = ProjectDocument(uri="u", path=Path("f"), source="x\ny")
        first = doc.lines
        second = doc.lines
        assert first is second


class TestProjectIndex:
    def _make_index(self, paths):
        node = _make_node("n", "/n")
        nodes_by_path = {p: [("file://test.arxml", node)] for p in paths}
        return ProjectIndex(
            documents={}, nodes_by_path=nodes_by_path, references_by_doc={}
        )

    def test_find_node_returns_entry_for_known_path(self):
        index = self._make_index(["/App"])
        result = index.find_node("/App")
        assert result is not None
        uri, _node = result
        assert uri == "file://test.arxml"

    def test_find_node_returns_none_for_unknown_path(self):
        index = self._make_index(["/App"])
        assert index.find_node("/Missing") is None

    def test_find_node_returns_first_entry_when_multiple_definitions(self):
        node_a = _make_node("A", "/App")
        node_b = _make_node("B", "/App")
        index = ProjectIndex(
            documents={},
            nodes_by_path={
                "/App": [("file://a.arxml", node_a), ("file://b.arxml", node_b)]
            },
            references_by_doc={},
        )
        uri, node = index.find_node("/App")
        assert uri == "file://a.arxml"
        assert node is node_a

    def test_path_exists_true_for_known_path(self):
        assert self._make_index(["/App"]).path_exists("/App") is True

    def test_path_exists_false_for_unknown_path(self):
        assert self._make_index(["/App"]).path_exists("/Missing") is False
