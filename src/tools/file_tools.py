import os
from pathlib import Path
import fnmatch

MAX_LINES_PER_READ = 500

_SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs"}


def find_files(pattern: str, directory: str = ".", max_results: int = 50) -> str:
    """
    Searches for files matching a glob pattern within a directory.
    Use this to find files by name or pattern (e.g., '*.py', 'test_*.py', '**/models/*.py').
    
    Pattern examples:
    - '*.py' - all .py files in directory
    - '**/*.py' - all .py files recursively
    - 'test_*.py' - files starting with test_
    - 'config.{json,yaml,xml}' - config.json, config.yaml, or config.xml
    
    Args:
        pattern: Glob pattern to match files
        directory: Starting directory for search (default: current directory)
        max_results: Maximum number of results to return (default: 50)
    """
    root = Path(directory).resolve()
    if not root.exists():
        return f"Directory not found: {directory}"
    
    if not pattern:
        return "Error: Pattern cannot be empty."
    
    matching_files = []
    original_count = 0
    
    try:
        # Handle ** pattern for recursive search
        if '**' in pattern:
            # Split into prefix and suffix for efficient walking
            if pattern.startswith('**/'):
                pattern_tail = pattern[3:]
                for dirpath, dirnames, filenames in os.walk(root):
                    # Skip common directories
                    dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
                    for filename in filenames:
                        if fnmatch.fnmatch(filename, pattern_tail):
                            original_count += 1
                            # Early exit if we've already exceeded max_results
                            if len(matching_files) >= max_results:
                                continue
                            full_path = Path(dirpath) / filename
                            try:
                                rel_path = full_path.relative_to(root)
                                matching_files.append(str(rel_path))
                            except ValueError:
                                matching_files.append(str(full_path))
            else:
                # Search from root
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
                    for filename in filenames:
                        original_count += 1
                        # Early exit if we've already exceeded max_results
                        if len(matching_files) >= max_results:
                            continue
                        rel_path = Path(dirpath) / filename
                        try:
                            rel_path_str = str(rel_path.relative_to(root))
                        except ValueError:
                            rel_path_str = str(rel_path)
                        if fnmatch.fnmatch(rel_path_str, pattern) or fnmatch.fnmatch(filename, pattern):
                            matching_files.append(str(rel_path.relative_to(root)))
        else:
            # Non-recursive search
            for filename in os.listdir(root):
                if fnmatch.fnmatch(filename, pattern):
                    original_count += 1
                    # Early exit if we've already exceeded max_results
                    if len(matching_files) >= max_results:
                        continue
                    try:
                        rel_path = (root / filename).relative_to(root)
                        matching_files.append(str(rel_path))
                    except ValueError:
                        matching_files.append(filename)
        
        # Add truncation message only if we actually found more than max_results
        if original_count > max_results:
            matching_files.append(f"\n... and {original_count - max_results} more files (max_results={max_results})")
        
        if not matching_files:
            return f"No files found matching pattern '{pattern}' in {directory}"
        
        return f"Found {original_count} files:\n" + "\n".join(matching_files)
    
    except PermissionError:
        return f"Permission denied accessing {directory}"
    except Exception as e:
        return f"Error searching files: {str(e)}"


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

        # Handle out-of-bounds start_line (already read entire file or invalid request)
        if start_line >= len(lines):
            return f"File already fully read (Lines {start_line+1}-{start_line+1} - File only has {len(lines)} lines total). Use a lower start_line or call read_file with no parameters to read from the beginning."
        
        chunk = lines[start_line:end_line]

        #Enforces max lines to prevent context window explosion
        if len(chunk) > MAX_LINES_PER_READ:
            chunk = chunk[:MAX_LINES_PER_READ]
            truncation_msg = f"\n[WARNING: Output truncated at {MAX_LINES_PER_READ} lines. Use start_line and end_line to read the rest.]"
        else:
            truncation_msg = ""

        # Format with line numbers (LLMs need line numbers to write accurate diffs/code)
        content_with_numbers = "".join([f"{i + start_line + 1:6d} | {line}" for i, line in enumerate(chunk)])

        # Return empty result if chunk is empty (end of file reached)
        if len(chunk) == 0:
            return f"File already fully read. Line range {start_line+1}-{start_line+1} is at end of file ({len(lines)} total lines)."
        
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
        return f"✅ Successfully edited {file_path} lines {start_line}-{end_line} ({old_lines_count}→{new_lines_count} lines)."

    except Exception as e:
        return f"Error applying diff to {file_path}: {str(e)}"
