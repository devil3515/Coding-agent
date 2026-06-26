from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

def load_prompt(prompt_name: str, fallback: str = "You are a helpful assistant.") -> str:
    """Fetches a prompt from a static .md file."""
    for ext in [".md", ".txt"]:
        prompt_file = PROMPTS_DIR / f"{prompt_name}{ext}"
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8").strip()

    return fallback