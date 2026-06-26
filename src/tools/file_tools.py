import os
from pathlib import Path

MAX_LINES_PER_READ = 500

_SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs"}


def get_file_tree(directory: str = ".", max_depth: int = 4) -> str:
    """
    Returns an indented directory tree of all files, skipping common build/cache dirs.
    Use this to see config files, markdown, templates and other non-code files before planning.
    """
    root = Path(directory).resolve()
    if not root.exists():
        return f"Directory not found: {directory}"

    lines = [str(root)]

    def _walk(path: Path, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            return
        for i, entry in enumerate(entries):
            if entry.name in _SKIP_DIRS or entry.name.startswith("."):
                continue
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if i == len(entries) - 1 else "│   "
                _walk(entry, prefix + extension, depth + 1)

    _walk(root, "", 1)
    return "\n".join(lines)

def read_file(file_path: str, start_line: int = 0, end_line: int = -1) -> str:
    """
    Reads a file and returns its content with line numbers.
    Use start_line and end_line to read specific chunks (0-indexed).
    """
    path = Path(file_path)
    if not path.exists():
        return f"File Not Found: {file_path}"

    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        #Handel line slicing
        if end_line == -1:
            end_line = len(lines)

        chunk = lines[start_line:end_line]

        #Enforces max lines to prevent context window explosion
        if len(chunk) > MAX_LINES_PER_READ:
            chunk = chunk[:MAX_LINES_PER_READ]
            truncation_msg = f"\n[WARNING: Output truncated at {MAX_LINES_PER_READ} lines. Use start_line and end_line to read the rest.]"
        else:
            truncation_msg = ""

        # Format with line numbers (LLMs need line numbers to write accurate diffs/code)
        content_with_numbers = "".join([f"{i + start_line + 1:6d} | {line}" for i, line in enumerate(chunk)])

        return f"--- File: {file_path} (Lines {start_line+1}-{start_line+len(chunk)}) ---\n{content_with_numbers}{truncation_msg}"

    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


def write_file(file_path: str, content: str) -> str:
    """
    OVERWRITES a file with the provided content. Creates parent directories if they don't exist.
    """
    path = Path(file_path)
    try:
        #Automaticall ycreate folders if they dont exists
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

        line_count = content.count('\n') + 1
        return f"Successfully wrote {line_count} lines to {file_path}"
    except Exception as e:
        return f"Error writing file {file_path}: {str(e)}"


def apply_diff(file_path: str, old_string: str, new_string: str) -> str:
    """
    Surgically edits a file by replacing an exact block of text.
    Use this for small, targeted changes instead of rewriting the whole file.
    """
    path = Path(file_path)
    if not path.exists():
        return f"Error: File '{file_path}' does not exist."

    try:
        content = path.read_text(encoding='utf-8')

        # Strict matching prevents the LLM from accidentally changing the wrong thing
        occurrences = content.count(old_string)

        if occurrences == 0:
            return f"Error: Could not find the exact `old_string` in {file_path}. The LLM likely missed some whitespace or indentation. Please use `read_file` to get the exact text, then try again."

        if occurrences > 1:
            return f"Error: Found {occurrences} matches for `old_string` in {file_path}. Please provide more surrounding lines to make the match unique."

        # Calculate exactly which lines are being changed (for LLM awareness)
        lines_before_change = content.split(old_string)[0]
        start_line = lines_before_change.count('\n') + 1
        old_lines_count = old_string.count('\n') + 1
        new_lines_count = new_string.count('\n') + 1
        end_line = start_line + old_lines_count - 1

        # Perform the replacement
        new_content = content.replace(old_string, new_string, 1)
        path.write_text(new_content, encoding='utf-8')

        # Return a rich, structured summary of what happened
        return (f"✅ Successfully edited {file_path} (Lines {start_line}-{end_line}).\n"
                f"   Replaced {old_lines_count} lines with {new_lines_count} lines.")

    except Exception as e:
        return f"Error applying diff to {file_path}: {str(e)}"
