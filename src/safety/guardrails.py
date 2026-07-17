import re
from pathlib import Path

DANGEROUS_SHELL_PATTERNS = [
    r'\brm\s+-[rf]+\s+/',     # Linux: rm -rf /
    r'\bdel\s+/[fFsS]\s+[A-Z]:', # Windows: del /F /S C:\
    r'\brmdir\s+/[sS]\s+[A-Z]:', # Windows: rmdir /S /Q C:\
    r'\bformat\b',              # Windows: format C:
    r'\bmkfs\b',                # Linux: mkfs
    r'\bsudo\b\s+rm\b',         # Linux: sudo rm
    r'\bshutdown\b',            # Both: shutdown commands
    r'\breg\s+delete',          # Windows registry deletion
]

def is_safe_path(requested_path: str, working_directory: str) -> tuple[bool, str]:
    """
    Checks if a requested file path is inside the working directory.
    Returns (is_safe, error_message).
    """
    try:
        work_dir = Path(working_directory).resolve()
        req_path = Path(requested_path)

        # FIRST: Check for symlinks in the requested path BEFORE resolving
        # Walk up from the base, checking each component
        parts = req_path.parts
        check_path = Path(parts[0]) if parts else Path("/")
        
        for i in range(1, len(parts)):
            check_path = check_path / parts[i]
            if check_path.is_symlink():
                # Resolve the symlink target and check if it's safe
                try:
                    target = check_path.resolve()
                    if not target.is_relative_to(work_dir):
                        return False, f"⛔ SECURITY ERROR: Symlink '{requested_path}' points outside working directory."
                except (OSError, RuntimeError):
                    return False, f"⛔ SECURITY ERROR: Cannot resolve symlink '{requested_path}'."
        
        # SECOND: Now resolve and check if resolved path is inside work directory
        try:
            req_resolved = req_path.resolve()
        except (OSError, RuntimeError):
            return False, f"⛔ SECURITY ERROR: Cannot resolve path '{requested_path}'."

        if not req_resolved.is_relative_to(work_dir):
            return False, f"⛔ SECURITY ERROR: Access denied. Path '{requested_path}' escapes the working directory '{working_directory}'."

        return True, ""
    except Exception as e:
        return False, f"⛔ SECURITY ERROR: Path validation failed: {str(e)}"

def is_shell_safe(command: str, working_directory: str) -> tuple[bool, str]:
    """
    Checks if a bash command is safe to run.
    We block obvious destructive commands, but allow standard tools like git, python, npm.
    """
    command = command.strip().lower()

    for pattern in DANGEROUS_SHELL_PATTERNS:
        if re.search(pattern, command):
            return False, f"⛔ SECURITY ERROR: Highly dangerous shell command blocked: {command}"

    if "../" in command or "..\\" in command:
        # We allow it ONLY if it's part of a standard git or python command, otherwise block.
        if not any(cmd in command for cmd in ["git ", "python ", "node ", "npm ", "uv "]):
             return False, f"⛔ SECURITY ERROR: Navigating outside the directory (../) is blocked."

    return True, ""
