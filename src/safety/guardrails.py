import re
from pathlib import Path

DANGEROUS_SHELL_PATTERNS = [
    r'\brm\s+-[rf]+\s+',           # Linux: rm -rf /, rm -rf /home, rm -rf ~
    r'\bdel\s+/[fFsS]+\s+[A-Z]:',  # Windows: del /F /S C:\
    r'\brmdir\s+/[sS]+\s+[A-Z]:',  # Windows: rmdir /S /Q C:\
    r'\bformat\b',                 # Windows: format C:
    r'\bmkfs\b',                   # Linux: mkfs
    r'\bsudo\b\s+rm\b',            # Linux: sudo rm
    r'\bshutdown\b',               # Both: shutdown commands
    r'\breg\s+delete',             # Windows registry deletion
    r'\bcurl\b.*\|.*\bsh\b',       # curl | sh
    r'\bwget\b.*\|.*\bsh\b',       # wget | sh
    r'\bnc\b\s+-[el]+\b',          # netcat listeners
    r'\bpython[23]?\s+-c\b',       # python -c (arbitrary code execution)
    r'\beval\b',                   # eval
]

def is_safe_path(requested_path: str, working_directory: str) -> tuple[bool, str]:
    """
    Checks if a requested file path is inside the working directory.
    Returns (is_safe, error_message).
    """
    try:
        work_dir = Path(working_directory).resolve()
        req_path = Path(requested_path).resolve()

        # Block symlinks that escape the working directory
        if req_path.is_symlink():
            real_path = req_path.readlink().resolve()
            if not real_path.is_relative_to(work_dir):
                return False, f"⛔ SECURITY ERROR: Symlink '{requested_path}' points outside the working directory."

        if not req_path.is_relative_to(work_dir):
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
            return False, f"⛔ SECURITY ERROR: Dangerous shell command blocked: {command}"

    if "../" in command or "..\\" in command:
        # We allow it ONLY if it's part of a standard git or python command, otherwise block.
        if not any(cmd in command for cmd in ["git ", "python ", "node ", "npm ", "uv "]):
            return False, f"⛔ SECURITY ERROR: Navigating outside the directory (../) is blocked."

    return True, ""