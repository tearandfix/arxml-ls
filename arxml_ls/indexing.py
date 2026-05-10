from pathlib import Path
from typing import Dict, List, Tuple

from lxml import etree
from pygls import uris
from pygls.lsp.server import LanguageServer

from .analysis import extract_reference_path
from .models import ArxmlNode, ProjectDocument, ProjectIndex


def build_arxml_tree(root: etree._Element) -> ArxmlNode:
    """Build a tree of ArxmlNodes from the XML element tree using SHORT-NAME tags."""
    root_node = ArxmlNode(name="", path="", element=root, children={})

    def process_element(elem: etree._Element, parent_node: ArxmlNode, parent_path: str):
        short_name = None
        for child in elem:
            tag_name = child.tag.split("}")[-1]
            if tag_name == "SHORT-NAME" and child.text:
                short_name = child.text.strip()
                break

        if short_name:
            node_path = f"{parent_path}/{short_name}"
            node = ArxmlNode(name=short_name, path=node_path, element=elem, children={})
            parent_node.children[short_name] = node
            for child in elem:
                process_element(child, node, node_path)
        else:
            for child in elem:
                process_element(child, parent_node, parent_path)

    for child in root:
        process_element(child, root_node, "")

    return root_node


def find_all_reference_elements(
    root: etree._Element,
) -> list[tuple[etree._Element, str, int, int]]:
    """Return (element, ref_path, line, column) for every -REF/-TREF in the tree."""
    references = []
    for elem in root.iter():
        ref_path = extract_reference_path(elem)
        if ref_path:
            line = elem.sourceline if hasattr(elem, "sourceline") else 0
            references.append((elem, ref_path, line, 0))
    return references


def _get_workspace_root(ls: LanguageServer, fallback_uri: str) -> Path:
    root_path_value = ls.workspace.root_path or ""
    if root_path_value:
        return Path(root_path_value)
    if fallback_uri:
        try:
            return Path(str(uris.to_fs_path(fallback_uri))).parent
        except Exception:
            pass
    return Path.cwd()


def _discover_arxml_files(ls: LanguageServer, fallback_uri: str) -> Dict[str, Path]:
    files: Dict[str, Path] = {}
    workspace_docs = getattr(ls.workspace, "documents", {})

    for doc in workspace_docs.values():
        doc_uri_obj = getattr(doc, "uri", None)
        if not doc_uri_obj or not isinstance(doc_uri_obj, str):
            continue
        try:
            doc_path = Path(str(uris.to_fs_path(doc_uri_obj))).resolve()
            files[doc_uri_obj] = doc_path
        except Exception:
            continue

    root_path = _get_workspace_root(ls, fallback_uri)
    if root_path.exists():
        for path in root_path.rglob("*.arxml"):
            resolved = path.resolve()
            uri_value = uris.from_fs_path(str(resolved))
            if not uri_value:
                continue
            files.setdefault(uri_value, resolved)

    if fallback_uri:
        try:
            fallback_path = Path(str(uris.to_fs_path(fallback_uri))).resolve()
            files.setdefault(fallback_uri, fallback_path)
        except Exception:
            pass

    return files


def _compute_workspace_state(
    ls: LanguageServer, files: Dict[str, Path]
) -> Tuple[Tuple[str, float | int | None], ...]:
    workspace_docs = getattr(ls.workspace, "documents", {})
    state: List[Tuple[str, float | int | None]] = []

    for uri, path in files.items():
        doc = workspace_docs.get(uri)
        if doc is not None:
            state.append((uri, doc.version))
        else:
            try:
                state.append((uri, path.stat().st_mtime_ns))
            except OSError:
                state.append((uri, None))

    return tuple(sorted(state, key=lambda item: item[0]))


def _register_nodes_for_document(
    doc_uri: str, node: ArxmlNode, registry: Dict[str, List[Tuple[str, ArxmlNode]]]
) -> None:
    for child in node.children.values():
        if child.path:
            registry.setdefault(child.path, []).append((doc_uri, child))
        _register_nodes_for_document(doc_uri, child, registry)


def _build_project_index(ls: LanguageServer, files: Dict[str, Path]) -> ProjectIndex:
    documents: Dict[str, ProjectDocument] = {}
    nodes_by_path: Dict[str, List[Tuple[str, ArxmlNode]]] = {}
    references_by_doc: Dict[str, List[Tuple[etree._Element, str, int, int]]] = {}

    workspace_docs = getattr(ls.workspace, "documents", {})

    for uri, path in files.items():
        source: str | None = None
        doc = workspace_docs.get(uri)
        if doc is not None:
            source = doc.source
        else:
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue

        if source is None:
            continue

        project_doc = ProjectDocument(uri=uri, path=path, source=source)

        try:
            root = etree.fromstring(source.encode("utf-8"))
            tree = build_arxml_tree(root)
            project_doc.root = root
            project_doc.tree = tree
            references_by_doc[uri] = find_all_reference_elements(root)
            _register_nodes_for_document(uri, tree, nodes_by_path)
        except Exception as exc:
            project_doc.parse_error = exc
            references_by_doc[uri] = []

        documents[uri] = project_doc

    return ProjectIndex(
        documents=documents,
        nodes_by_path=nodes_by_path,
        references_by_doc=references_by_doc,
    )


def _get_project_index(ls: LanguageServer, current_uri: str) -> ProjectIndex:
    files = _discover_arxml_files(ls, current_uri)
    state = _compute_workspace_state(ls, files)
    cache = getattr(ls, "_project_index_cache", None)

    if cache and cache.get("state") == state:
        cached_index = cache.get("index")
        if cached_index:
            return cached_index

    index = _build_project_index(ls, files)
    setattr(ls, "_project_index_cache", {"state": state, "index": index})
    return index
