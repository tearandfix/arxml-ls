import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from lxml import etree


REF_TAG_PATTERN = re.compile(
    r"<[^>]*?-(?:T?REF)(?![A-Z0-9_-])[^>]*>([^<]+)</[^>]*?-(?:T?REF)(?![A-Z0-9_-])[^>]*>"
)


@dataclass
class ArxmlNode:
    name: str  # SHORT-NAME value
    path: str  # Full path from root (e.g., /Application/Executables/Test)
    element: etree._Element
    children: dict[str, "ArxmlNode"] = field(default_factory=dict)

    def find_by_path(self, path: str) -> "ArxmlNode | None":
        if path == self.path:
            return self
        if path.startswith("/"):
            path = path[1:]
        parts = path.split("/")
        current = self
        for part in parts:
            if part in current.children:
                current = current.children[part]
            else:
                return None
        return current


@dataclass
class ProjectDocument:
    uri: str
    path: Path
    source: str
    root: etree._Element | None = None
    tree: ArxmlNode | None = None
    parse_error: Exception | None = None
    _lines: List[str] | None = field(default=None, init=False, repr=False)

    @property
    def lines(self) -> List[str]:
        if self._lines is None:
            self._lines = self.source.splitlines()
        return self._lines


@dataclass
class ProjectIndex:
    documents: Dict[str, ProjectDocument]
    nodes_by_path: Dict[str, List[Tuple[str, ArxmlNode]]]
    references_by_doc: Dict[str, List[Tuple[etree._Element, str, int, int]]]

    def find_node(self, path: str) -> Tuple[str, ArxmlNode] | None:
        matches = self.nodes_by_path.get(path)
        if matches:
            return matches[0]
        return None

    def path_exists(self, path: str) -> bool:
        return path in self.nodes_by_path
