import json
import os


def load_config(config_path):
    """Load and parse the JSON config file. Raises with a clear message on failure."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Config file '{config_path}' is not valid JSON: {e}") from e


def get_required_env(name):
    """Fetch a required secret from the environment, failing fast if it's missing."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            "Secrets are read from the environment, never from config.json."
        )
    return value
