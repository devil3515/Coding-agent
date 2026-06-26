import os
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

from .graph import CodeGraph, Node, Edge

class GraphExtractor:
    def __init__(self):
        self.graph = CodeGraph()

        # THE LANGUAGE MAP
        # Maps file extensions to their Tree-sitter grammars
        self.languages = {
            ".py": Language(tspython.language()),
            ".js": Language(tsjs.language()),
            ".jsx": Language(tsjs.language()),
            ".ts": Language(tsts.language_typescript()),
            ".tsx": Language(tsts.language_tsx()),
            # You can add more here later:
            # ".go": Language(ts_go.language()),
            # ".rs": Language(ts_rust.language()),
        }

    def index_file(self, file_path: str):
        """Reads a file, picks the right parser, and extracts nodes/edges"""
        ext = os.path.splitext(file_path)[1]
        lang = self.languages.get(ext)

        # If we don't support this language, skip it silently
        if not lang:
            return

        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()

        # Initialize the parser with the SPECIFIC language for this file
        parser = Parser(lang)
        tree = parser.parse(bytes(code, "utf8"))

        # Walk the tree
        self._walk_tree(tree.root_node, file_path, ext)

    def _walk_tree(self, node, file_path: str, ext: str):
        """Recursively walks the AST, adapting to the current language"""

        # --- LANGUAGE AGNOSTIC NODE MATCHING ---
        # We check the node type based on what language we are parsing
        node_type = node.type
        is_function = False
        is_class = False

        if ext == ".py":
            is_function = node_type == "function_definition"
            is_class = node_type == "class_definition"
        elif ext in (".js", ".jsx", ".ts", ".tsx"):
            # JS/TS have multiple ways to define functions
            is_function = node_type in ("function_declaration", "arrow_function", "generator_function_declaration")
            is_class = node_type == "class_declaration"

        # --- EXTRACT NODES ---
        if is_function:
            func_name_node = node.child_by_field_name('name')
            if func_name_node:
                func_name = func_name_node.text.decode('utf-8')
                node_id = f"{file_path}:{func_name}"

                self.graph.add_node(Node(
                    id=node_id, type="function", name=func_name,
                    file_path=file_path, line_number=node.start_point[0] + 1,
                    metadata={}
                ))
                self._extract_calls(node, node_id)

        elif is_class:
            class_name_node = node.child_by_field_name('name')
            if class_name_node:
                class_name = class_name_node.text.decode('utf-8')
                node_id = f"{file_path}:{class_name}"
                self.graph.add_node(Node(
                    id=node_id, type="class", name=class_name,
                    file_path=file_path, line_number=node.start_point[0] + 1,
                    metadata={}
                ))

        # Recurse into children
        for child in node.children:
            self._walk_tree(child, file_path, ext)

    def _extract_calls(self, func_node, source_node_id: str):
        """Finds all function calls inside a function block (Works across most languages)"""
        # The 'call' node type is surprisingly consistent across Python, JS, and TS!
        if func_node.type == 'call':
            func_to_call = func_node.child_by_field_name('function')
            if func_to_call:
                # Handle chained calls like `db.users.find()` - just get 'find'
                if func_to_call.type == 'member_expression':
                    # The last child is usually the method name
                    method_node = func_to_call.child_by_field_name('property') or func_to_call.children[-1]
                    called_name = method_node.text.decode('utf-8')
                else:
                    called_name = func_to_call.text.decode('utf-8')

                target_id = f"UNKNOWN:{called_name}"
                self.graph.add_edge(Edge(source=source_node_id, target=target_id, type="calls"))

        for child in func_node.children:
            self._extract_calls(child, source_node_id)

    def index_directory(self, dir_path: str):
        """Indexes an entire project directory"""
        for root, _, files in os.walk(dir_path):
            # Skip hidden folders and common non-code directories
            if '/.' in root or 'node_modules' in root or 'venv' in root or '.venv' in root:
                continue

            for file in files:
                self.index_file(os.path.join(root, file))