import yaml
import os
from pathlib import Path

# Defaults for the harness section (read budget, scratchpad auto-injection,
# scratchpad size cap). Used when config.yaml is missing the section entirely
# or any of its keys. The harness is the agent's general working-memory and
# pacing system — not debug-specific.
HARNESS_DEFAULTS = {
    "read_budget": 5,                # soft cap on read-only tool calls per turn
    "scratchpad_inject_tokens": 800, # max tokens of scratchpad auto-injected per turn
    "scratchpad_max_chars": 20000,   # safety cap on a single update_scratchpad call
}


def load_settings():

    config_path = Path(__file__).parent.parent.parent / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Missing config.yaml at {config_path}")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    api_key = config.get('llm', {}).get('api_key', '')
    if isinstance(api_key, str) and api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        config['llm']['api_key'] = os.getenv(env_var, "")

    # Merge harness config with defaults so the rest of the codebase
    # can rely on every key being present.
    raw = config.get("harness", {}) or {}
    merged = dict(HARNESS_DEFAULTS)
    for key, default in HARNESS_DEFAULTS.items():
        if key in raw:
            value = raw[key]
            # Coerce types: YAML may give us a string for ints, etc.
            if isinstance(default, int):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = default
            merged[key] = value
    config["harness"] = merged

    return config