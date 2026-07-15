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


## CONFIGURATION VARIABLES (from config.yaml at the repo root; defaults below) ##
URL = _cfg.get("eln_url", "https://eln.ddomlab.org/api/v2")
PRINTER_PATH = _path(_cfg.get("printer_path", "/tmp/label.pdf"))
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
