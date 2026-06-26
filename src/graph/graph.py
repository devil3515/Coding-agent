from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class Node:
    id: str
    type: str
    name: str
    file_path: str
    line_number: int
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Edge:
    source: str
    target: str
    type: str


class CodeGraph:
    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        #adjacency for lightning fast lookups
        self.adjacency: Dict[str, List[str]] = {}

    def add_node(self, node: Node):
        self.nodes[node.id] = node
        if node.id not in self.adjacency:
            self.adjacency[node.id] = []

    def add_edge(self, edge: Edge):
        self.edges.append(edge)
        if edge.source not in self.adjacency:
            self.adjacency[edge.source] = []
        self.adjacency[edge.source].append(edge.target)

    def get_node(self, name: str) -> List[Node]:
        """Find all nodes matching a name (e.g., find all functions named 'login')"""
        return [n for n in self.nodes.values() if name.lower() in n.name.lower()]

    def get_callers(self, node_id: str) -> List[Node]:
        """Who calls this function?"""
        callers = []
        for edge in self.edges:
            if edge.target == node_id and edge.type == "calls":
                callers.append(self.nodes.get(edge.source))
        return [c for c in callers if c is not None]

    def to_llm_context(self, nodes: List[Node], edges: List[Edge]) -> str:
        """Formats the graph into a highly readable string for the LLM"""
        output = "===CodeBase Graph Context===\n"
        for node in nodes:
            output += f"- [{node.type.upper()}] {node.name} (File: {node.file_path}, Line: {node.line_number})\n"
        for edge in edges:
            output += f"  -> {edge.source} [{edge.type}] {edge.target}\n"
        return output