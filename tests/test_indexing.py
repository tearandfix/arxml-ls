from lxml import etree

from arxml_ls.indexing import (
    _register_nodes_for_document,
    build_arxml_tree,
    find_all_reference_elements,
)


class TestBuildArxmlTree:
    def test_root_node_has_empty_name_and_path(self, arxml_root):
        tree = build_arxml_tree(arxml_root)
        assert tree.name == ""
        assert tree.path == ""

    def test_top_level_package_is_registered(self, arxml_root):
        tree = build_arxml_tree(arxml_root)
        assert "Application" in tree.children
        node = tree.children["Application"]
        assert node.name == "Application"
        assert node.path == "/Application"

    def test_nested_package_is_registered_under_parent(self, arxml_root):
        tree = build_arxml_tree(arxml_root)
        comp = tree.children["Application"].children["Components"]
        assert comp.name == "Components"
        assert comp.path == "/Application/Components"

    def test_leaf_element_is_registered(self, arxml_root):
        tree = build_arxml_tree(arxml_root)
        leaf = (
            tree.children["Application"].children["Components"].children["MyComponent"]
        )
        assert leaf.name == "MyComponent"
        assert leaf.path == "/Application/Components/MyComponent"

    def test_elements_without_short_name_are_transparent(self, arxml_root):
        # Root should only have "Application" as a child — AR-PACKAGES is transparent
        tree = build_arxml_tree(arxml_root)
        assert list(tree.children.keys()) == ["Application"]

    def test_find_by_path_works_on_built_tree(self, arxml_root):
        tree = build_arxml_tree(arxml_root)
        node = tree.find_by_path("/Application/Components/MyComponent")
        assert node is not None
        assert node.name == "MyComponent"


class TestFindAllReferenceElements:
    def test_finds_ref_elements(self):
        xml = (
            "<AUTOSAR>"
            "<COMPONENT-REF>/Application/Comp</COMPONENT-REF>"
            "<OTHER-REF>/Other/Path</OTHER-REF>"
            "</AUTOSAR>"
        )
        root = etree.fromstring(xml.encode())
        refs = find_all_reference_elements(root)
        paths = [r[1] for r in refs]
        assert "/Application/Comp" in paths
        assert "/Other/Path" in paths

    def test_returns_empty_list_when_no_refs(self):
        xml = "<AUTOSAR><SHORT-NAME>Foo</SHORT-NAME></AUTOSAR>"
        root = etree.fromstring(xml.encode())
        assert find_all_reference_elements(root) == []

    def test_each_entry_has_four_fields(self):
        xml = "<AUTOSAR><COMPONENT-REF>/A/B</COMPONENT-REF></AUTOSAR>"
        root = etree.fromstring(xml.encode())
        refs = find_all_reference_elements(root)
        assert len(refs) == 1
        _elem, path, line, col = refs[0]
        assert path == "/A/B"
        assert isinstance(line, int)
        assert col == 0

    def test_ignores_non_ref_tags(self):
        xml = "<AUTOSAR><SHORT-NAME>Name</SHORT-NAME><COMPONENT-REF>/A</COMPONENT-REF></AUTOSAR>"
        root = etree.fromstring(xml.encode())
        refs = find_all_reference_elements(root)
        assert len(refs) == 1
        assert refs[0][1] == "/A"


class TestRegisterNodesForDocument:
    def test_all_paths_registered(self, arxml_tree):
        registry = {}
        _register_nodes_for_document("file://test.arxml", arxml_tree, registry)
        assert "/Application" in registry
        assert "/Application/Components" in registry
        assert "/Application/Components/MyComponent" in registry

    def test_each_path_maps_to_correct_uri(self, arxml_tree):
        registry = {}
        _register_nodes_for_document("file://test.arxml", arxml_tree, registry)
        uri, node = registry["/Application"][0]
        assert uri == "file://test.arxml"
        assert node.name == "Application"

    def test_root_path_not_registered(self, arxml_tree):
        # Root node has path="" and should not be added
        registry = {}
        _register_nodes_for_document("file://test.arxml", arxml_tree, registry)
        assert "" not in registry

    def test_accumulates_across_multiple_calls(self, arxml_tree):
        registry = {}
        _register_nodes_for_document("file://a.arxml", arxml_tree, registry)
        _register_nodes_for_document("file://b.arxml", arxml_tree, registry)
        assert len(registry["/Application"]) == 2
        uris = [uri for uri, _ in registry["/Application"]]
        assert "file://a.arxml" in uris
        assert "file://b.arxml" in uris
