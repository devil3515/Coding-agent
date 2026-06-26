import yaml
import os
from pathlib import Path

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

    return config