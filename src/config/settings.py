import yaml
import os
from pathlib import Path
from typing import Any, Dict


def load_settings() -> Dict[str, Any]:
    """Load settings from config.yaml file."""

    config_path = Path(__file__).parent.parent.parent / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Missing config.yaml at {config_path}")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    api_key = config.get('llm', {}).get('api_key', '')
    if isinstance(api_key, str) and api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        config['llm']['api_key'] = os.getenv(env_var, "")

    return config


def get_memory_sprint1_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get Sprint 1 memory configuration with safe defaults.

    Args:
        config: Full configuration dictionary.

    Returns:
        Dictionary with Sprint 1 config values.
    """
    default_sprint1 = {
        "enabled": False,
        "redact_secrets": True,
        "checkpoint_every_step": True,
        "max_checkpoint_observation_chars": 2000,
        "max_recent_turns_in_context": 12,
    }

    memory_config = config.get("memory", {})
    sprint1_config = memory_config.get("sprint1", {})

    # Merge with defaults
    return {**default_sprint1, **sprint1_config}