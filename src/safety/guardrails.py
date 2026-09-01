"""Safety guardrails for file and shell operations."""
import re
from pathlib import Path

DANGEROUS_SHELL_PATTERNS = [
    r'rm\s+-[rf]+\s+',
    r'del\s+/[fFsS]+\s+[A-Z]:',
    r'rmdir\s+/[sS]+\s+[A-Z]:',
    r'format',
    r'mkfs',
    r'sudo\s+rm',
    r'shutdown',
    r'reg\s+delete',
    r'curl.*\|.*sh',
    r'wget.*\|.*sh',
    r'nc\s+-[el]+',
    r'python[23]?\s+-c',
    r'eval',
]


def is_safe_path(requested_path: str, working_directory: str) -> tuple[bool, str]:
    """
    Checks if a requested file path is inside the working directory.
    Blocks symlinks that point outside the working directory.
    """
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
    """Checks if a bash command is safe to run."""
    command_lower = command.strip().lower()

    for pattern in DANGEROUS_SHELL_PATTERNS:
        if re.search(pattern, command_lower):
            return (
                False,
                f"⛔ SECURITY ERROR: Dangerous shell command blocked: {command}",
            )

    if "../" in command_lower or "..\\" in command_lower:
        allowed_cmds = [
            "git ", "python ", "python3 ", "node ", "npm ", "uv ", "cargo ",
            "sed ", "echo ", "printf ", "cat ", "cp ", "mv ", "touch "
        ]
        if not any(cmd in command_lower for cmd in allowed_cmds):
            try:
                work_path = Path(working_directory).resolve()
                for token in re.split(r'[\s;&|]+', command):
                    token_clean = token.strip('"\'')
                    if "../" in token_clean or "..\\" in token_clean:
                        resolved = (work_path / token_clean).resolve()
                        if not resolved.is_relative_to(work_path):
                            return (
                                False,
                                "⛔ SECURITY ERROR: Navigating outside the working directory (../) is blocked.",
                            )
            except Exception:
                return (
                    False,
                    "⛔ SECURITY ERROR: Navigating outside the working directory (../) is blocked.",
                )

    return True, ""