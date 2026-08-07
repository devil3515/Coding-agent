from src.graph.extractor import GraphExtractor

#Cache the graph instgance so we dont reparse the graph on every tool call
_graph_cache = None
_graph_directory = None


def _build_graph(project_dir: str):
    global _graph_cache, _graph_directory
    if _graph_cache is None or _graph_directory != project_dir:
        extractor = GraphExtractor()
        extractor.index_directory(project_dir)
        _graph_cache = extractor.graph
        _graph_directory = project_dir


def search_codebase(query: str, project_dir: str = ".") -> str:
    """
    Searches the local codebase graph for functions, classes, and their relationships.
    Use this tool to understand how the project works, where functions are defined, and what calls what.
    """
    try:
        _build_graph(project_dir)

        #1. Find nodes matching the query
        matched_nodes = _graph_cache.get_node(query)
        if matched_nodes:
            matched_nodes = [n for n in matched_nodes if "parallel_agent.py" not in getattr(n, "file_path", "")]

        if not matched_nodes:
            return f"No functions, classes, or variables found matching '{query}'."

        #2. Find who callls thes nodes to give the llm context
        context_lines = []
        for node in matched_nodes:
            context_lines.append(f"- [{node.type.upper()}] {node.name} (File: {node.file_path}, Line: {node.line_number})")

            callers = _graph_cache.get_callers(node.id)
            for caller in callers:
                context_lines.append(f"  ↳ Called by: {caller.name} in {caller.file_path}")

            #Find what this node calls
            if node.id in _graph_cache.adjacency:
                for target_id in _graph_cache.adjacency[node.id]:
                    # Just print the name part of the target ID (e.g., "UNKNOWN:db.query" -> "db.query")
                    target_name = target_id.split(":")[-1] if ":" in target_id else target_id
                    context_lines.append(f"  ↳ Calls: {target_name}")

        return "\n".join(context_lines)
    except Exception as e:
        return f"Error parsing codebase: {str(e)}"


def get_codebase_overview(project_dir: str = ".") -> str:
    """
    Returns every file in the project with all its functions and classes listed.
    Call this BEFORE create_project_plan so you know exactly which files to reference in each step.
    """
    try:
        _build_graph(project_dir)

        # Group nodes by file path
        files: dict[str, list] = {}
        for node in _graph_cache.nodes.values():
            files.setdefault(node.file_path, []).append(node)

        if not files:
            return "No code symbols found. The directory may be empty or contain no supported files (.py, .js, .ts, .tsx)."

        # Sort files and symbols within each file by line number
        lines = [f"=== Codebase Overview ({len(files)} files, {len(_graph_cache.nodes)} symbols) ===\n"]
        for file_path in sorted(files.keys()):
            if "parallel_agent.py" in file_path:
                continue
            nodes = sorted(files[file_path], key=lambda n: n.line_number)
            lines.append(file_path)
            for node in nodes:
                lines.append(f"  [{node.type.upper():<8}] {node.name}  (line {node.line_number})")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"Error generating codebase overview: {str(e)}"

