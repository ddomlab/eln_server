import os
from pathlib import Path

import elabapi_python
import urllib3
import yaml

current_dir = Path(__file__).parent
PROJECT_ROOT = current_dir.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _load_config_file() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}


def _path(value: str) -> str:
    """Resolve a configured path relative to the repo root (absolute paths pass through)."""
    return str(PROJECT_ROOT / Path(os.path.expanduser(value)))


_cfg = _load_config_file()

# Secrets (the eLN API key fallback and the Slack bot token) live in a
# gitignored secrets.yaml at the repo root; see secrets.example.yaml.
SECRETS_PATH = PROJECT_ROOT / "secrets.yaml"


def get_secret(name: str) -> str | None:
    """Read one field from secrets.yaml. Loaded lazily on each call so the
    server can start before the file exists and pick it up once filled in."""
    try:
        with open(SECRETS_PATH) as f:
            secrets = yaml.safe_load(f)
    except FileNotFoundError:
        return None
    if not isinstance(secrets, dict):
        return None
    value = secrets.get(name)
    return str(value).strip() if value else None


def _require(key: str) -> str:
    """Fetch a config value that has no sensible lab-agnostic default."""
    value = _cfg.get(key)
    if not value:
        raise ValueError(f"'{key}' must be set in {CONFIG_PATH}")
    return str(value)


## CONFIGURATION VARIABLES (from config.yaml at the repo root) ##
# The instance URLs are deliberately not defaulted: every lab must point the
# server at its own eLabFTW before anything runs.
URL = _require("eln_url").rstrip("/")
WEB_URL = _require("eln_web_url").rstrip("/")
PRINTER_PATH = _path(_cfg.get("printer_path", "/tmp/label.pdf"))


def item_web_url(item_id) -> str:
    """Link to a resource's page in the eLabFTW web UI."""
    return f"{WEB_URL}/database.php?mode=view&id={item_id}"


# Team-specific status/category IDs (see config.yaml for how to look them up).
# Re-read from config.yaml on every call — unlike the startup constants above —
# so changes made via the web settings page apply to all gunicorn workers
# without a restart.
def setting(key: str, default):
    return _load_config_file().get(key, default)


def update_settings(values: dict) -> None:
    """Rewrite the given top-level keys in config.yaml in place, appending any
    that are missing. Line-based on purpose: a yaml round-trip would drop the
    file's comments."""
    def render(v) -> str:
        if isinstance(v, list):
            return "[" + ", ".join(str(x) for x in v) + "]"
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    lines = CONFIG_PATH.read_text().splitlines() if CONFIG_PATH.exists() else []
    for key, value in values.items():
        new_line = f"{key}: {render(value)}"
        for i, line in enumerate(lines):
            if line.startswith(f"{key}:"):
                lines[i] = new_line
                break
        else:
            lines.append(new_line)
    CONFIG_PATH.write_text("\n".join(lines) + "\n")
# Legacy feature: /print used to fetch a label.pdf stored on each resource, so
# autofill uploaded one to every new item. /print now generates labels on the
# fly, making the uploads redundant; set auto_upload_labels: true in
# config.yaml to keep attaching label.pdf to resources anyway.
AUTO_UPLOAD_LABELS = bool(_cfg.get("auto_upload_labels", False))
##################################################

# allows the connection
urllib3.disable_warnings()


def get_api_key(key: str | None = None):
    """Build an elabapi client from the given key, or fall back to the
    eln_api_key entry in secrets.yaml (used by the one-off scripts in scripts/;
    server requests always pass the caller's key)."""
    if key is None:
        key = get_secret("eln_api_key")
        if not key:
            raise ValueError(
                f"No API key provided and no eln_api_key set in {SECRETS_PATH}"
            )
    configuration = elabapi_python.Configuration()
    configuration.api_key["api_key"] = key
    configuration.api_key_prefix["api_key"] = "Authorization"
    configuration.host = URL
    configuration.debug = False
    configuration.verify_ssl = False

    # create an instance of the API class
    api_client = elabapi_python.ApiClient(configuration)

    # fix issue with Authorization header not being properly set by the generated lib
    api_client.set_default_header(header_name="Authorization", header_value=key)
    return api_client


def load_items_api(key=None):
    return elabapi_python.ItemsApi(get_api_key(key))


def load_experiments_api(key=None):
    return elabapi_python.ExperimentsApi(get_api_key(key))


def load_uploads_api(key=None):
    return elabapi_python.UploadsApi(get_api_key(key))


def load_api(key=None):
    return get_api_key(key)
