import os
from pathlib import Path

import elabapi_python
import urllib3

current_dir = Path(__file__).parent
## CONFIGURATION VARIABLES ##
# Interactive/API callers pass their own eLabFTW API key with each request, so the
# server itself does not need a key file. A local 'api_key' file (gitignored) is
# still supported as a fallback for running the one-off scripts in scripts/.
# New api keys can be generated at https://eln.ddomlab.org/ucp.php?tab=4
API_KEY_PATH = os.environ.get("ELN_API_KEY_PATH", str(current_dir / "api_key"))
URL = os.environ.get("ELN_URL", "https://eln.ddomlab.org/api/v2")
PRINTER_PATH = os.environ.get("ELN_PRINTER_PATH", "/tmp/label.pdf")
##################################################

# allows the connection
urllib3.disable_warnings()


def get_api_key(key: str | None = None):
    """Build an elabapi client from the given key, or fall back to the local api_key file."""
    if key is None:
        try:
            with open(API_KEY_PATH) as keyfile:
                key = keyfile.read().strip()
        except FileNotFoundError:
            raise ValueError(
                "No API key provided and no api_key file found at " + API_KEY_PATH
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
