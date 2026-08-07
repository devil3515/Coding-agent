"""Safety guardrails for file and shell operations."""
import re
from pathlib import Path

DANGEROUS_SHELL_PATTERNS = [
    r'\brm\s+-[rf]+\s+',           # rm -rf /, rm -rf /home
    r'\bdel\s+/[fFsS]+\s+[A-Z]:',  # Windows: del /F C:\
    r'\brmdir\s+/[sS]+\s+[A-Z]:',  # Windows: rmdir /S C:\
    r'\bformat\b',
    r'\bmkfs\b',
    r'\bsudo\b\s+rm\b',
    r'\bshutdown\b',
    r'\breg\s+delete',
    r'\bcurl\b.*\|.*\bsh\b',
    r'\bwget\b.*\|.*\bsh\b',
    r'\bnc\b\s+-[el]+\b',
    r'\bpython[23]?\s+-c\b',
    r'\beval\b',
]


def is_safe_path(requested_path: str, working_directory: str) -> tuple[bool, str]:
    try:
        work_dir = Path(working_directory).resolve()
        req_path = Path(requested_path)
        resolved_path = req_path.resolve()

        if not resolved_path.is_relative_to(work_dir):
            return (
                False,
                f"⛔ SECURITY ERROR: Access denied. Path '{requested_path}' "
                f"escapes the working directory '{working_directory}'.",
            )

        # Block symlinks pointing outside
        if req_path.is_symlink():
            real_target = req_path.readlink()
            if real_target.is_absolute():
                real_resolved = real_target.resolve()
                if not real_resolved.is_relative_to(work_dir):
                    return (
                        False,
                        f"⛔ SECURITY ERROR: Symlink '{requested_path}' points "
                        f"outside the working directory.",
                    )

        return True, ""
    except Exception as e:
        return False, f"⛔ SECURITY ERROR: Path validation failed: {str(e)}"


def is_shell_safe(command: str, working_directory: str) -> tuple[bool, str]:
    command = command.strip().lower()

    for pattern in DANGEROUS_SHELL_PATTERNS:
        if re.search(pattern, command):
            return (
                False,
                f"⛔ SECURITY ERROR: Dangerous shell command blocked: {command}",
            )

    if "../" in command or "..\\" in command:
        if not any(cmd in command for cmd in ["git ", "python ", "node ", "npm ", "uv "]):
            return (
                False,
                f"⛔ SECURITY ERROR: Navigating outside the directory (../) is blocked.",
            )

    return True, ""