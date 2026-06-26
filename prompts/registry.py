import datetime
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent

def _load_static_prompt(filename: str) -> str:
    """Loads a static .md prompt template from disk."""
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing prompt file: {path}")
    return path.read_text(encoding="utf-8")


def get_default_prompt(working_dir: str = "Unknown") -> str:
    """
    Loads the full system prompt (rules, protocols, Ponytail discipline,
    etc.) from disk, then appends dynamic runtime facts that change
    every session — these CANNOT live in the static file since they're
    only known at startup.
    """
    base_prompt = _load_static_prompt("default.md")
    today = datetime.date.today().strftime("%Y-%m-%d")

    dynamic_context = f"""

## Runtime Context (Injected — Do Not Edit)
- Working directory: `{working_dir}`
- Today's date: {today}
"""

    return base_prompt + dynamic_context


def get_planning_prompt() -> str:
    return _load_static_prompt("planning.md")