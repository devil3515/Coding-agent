"""Scratchpad working-memory tool for the coding agent.

The scratchpad is a single markdown file the agent owns and the harness
re-injects into every system message. The agent uses it to record its
current hypothesis, what it has already read or ruled out, and what it
plans to investigate next. This stops it from re-reading the same files
across turns during long debug sessions.

The path is fixed by the harness (.agent-audit/scratchpad.md) so the LLM
cannot choose an arbitrary location. The file lives inside the working
directory so the existing safety sandbox (is_safe_path) applies.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

SCRATCHPAD_RELATIVE_PATH = ".agent-audit/scratchpad.md"
MISSING_SCRATCHPAD_MESSAGE = (
    "[No scratchpad yet — call update_scratchpad to start one. "
    "It is your working memory.]"
)


def _scratchpad_path(working_directory: str) -> Path:
    """Return the absolute path to the scratchpad file."""
    if not working_directory:
        working_directory = "."
    return Path(working_directory).resolve() / SCRATCHPAD_RELATIVE_PATH


def _read(working_directory: str) -> str:
    """Internal: read the scratchpad file. Returns empty string if missing."""
    path = _scratchpad_path(working_directory)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception as e:
        return f"[Error reading scratchpad: {e}]"


def update_scratchpad(content: str, working_directory: str, max_chars: int = 20000) -> str:
    """Overwrite the scratchpad file with the given markdown content.

    The path is owned by the harness. Returns a short status string the
    LLM can use as the tool result; never raises.
    """
    if not working_directory:
        return "Error: working_directory is not set; cannot write scratchpad."

    if not isinstance(content, str):
        return f"Error: content must be a string, got {type(content).__name__}."

    if len(content) > max_chars:
        return (
            f"Error: scratchpad content is {len(content)} chars, which exceeds "
            f"the safety cap of {max_chars}. Trim and try again."
        )

    path = _scratchpad_path(working_directory)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except Exception as e:
        return f"Error writing scratchpad: {e}"

    line_count = content.count("\n") + (1 if content else 0)
    return (
        f"✅ Scratchpad updated: {len(content)} chars, {line_count} lines "
        f"written to {SCRATCHPAD_RELATIVE_PATH}."
    )


def read_scratchpad(working_directory: str) -> str:
    """Return the current scratchpad contents, or a clear 'not yet' message."""
    content = _read(working_directory)
    if not content.strip():
        return MISSING_SCRATCHPAD_MESSAGE
    return content


def get_scratchpad_summary(
    working_directory: str,
    max_chars: int = 3200,
) -> dict:
    """Return a structured summary used by the agent for auto-injection.

    The agent's _build_context() calls this every turn and decides whether
    to truncate, whether the file is empty, etc. Truncation is by character
    count, not tokens, because the caller will pass `max_chars` derived
    from the configured token cap (≈4 chars per token).
    """
    path = _scratchpad_path(working_directory)
    exists = path.exists()
    if not exists:
        return {
            "exists": False,
            "path": SCRATCHPAD_RELATIVE_PATH,
            "content": "",
            "line_count": 0,
            "char_count": 0,
            "modified_at": None,
            "truncated": False,
        }

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return {
            "exists": True,
            "path": SCRATCHPAD_RELATIVE_PATH,
            "content": f"[Error reading scratchpad: {e}]",
            "line_count": 0,
            "char_count": 0,
            "modified_at": None,
            "truncated": False,
        }

    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        modified_at = mtime.isoformat()
    except Exception:
        modified_at = None

    if not content.strip():
        return {
            "exists": True,
            "path": SCRATCHPAD_RELATIVE_PATH,
            "content": "",
            "line_count": 0,
            "char_count": 0,
            "modified_at": modified_at,
            "truncated": False,
        }

    truncated = False
    if len(content) > max_chars:
        content = content[:max_chars]
        truncated = True

    return {
        "exists": True,
        "path": SCRATCHPAD_RELATIVE_PATH,
        "content": content,
        "line_count": content.count("\n") + 1,
        "char_count": len(content),
        "modified_at": modified_at,
        "truncated": truncated,
    }
