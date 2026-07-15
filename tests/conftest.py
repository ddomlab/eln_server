"""
Shared fixtures for the eln_server test suite.

Two kinds of tests:
  - offline: routing, auth plumbing, and input validation; no eLN key needed.
  - live (marked @pytest.mark.live): run against the real eLabFTW server as the
    key found via $ELN_TEST_API_KEY, or the ELN_API_KEY entry in the yaml file
    at $ELN_TEST_API_KEY_FILE. Live tests only touch resource TEST_ITEM_ID and
    restore its state afterwards.

Slack is stubbed out for every test so a failing run can never post to the lab
channels; the `slack_messages` fixture exposes what would have been sent.
"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# The one resource the suite is allowed to modify.
TEST_ITEM_ID = 393

DEFAULT_KEY_FILE = "/home/kyle/Desktop/DDOM/MEDUSA/code/MEDUSA/config/apikey.yaml"
KEY_TAG = "ELN_API_KEY"


def _load_api_key() -> str | None:
    key = os.environ.get("ELN_TEST_API_KEY")
    if key:
        return key
    path = os.environ.get("ELN_TEST_API_KEY_FILE", DEFAULT_KEY_FILE)
    try:
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and data.get(KEY_TAG):
            return data[KEY_TAG]
    except (FileNotFoundError, ImportError):
        pass
    # fall back to the project's own secrets.yaml
    from eln_common.config import get_secret
    return get_secret("eln_api_key")


@pytest.fixture(scope="session")
def api_key() -> str:
    key = _load_api_key()
    if not key:
        pytest.skip(
            "No eLN API key: set $ELN_TEST_API_KEY or provide the "
            f"{KEY_TAG} tag in {DEFAULT_KEY_FILE}"
        )
    return key


@pytest.fixture(scope="session")
def flask_app():
    from app import app
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture()
def auth_headers(api_key):
    return {"Authorization": f"Bearer {api_key}"}


@pytest.fixture()
def live_rm(api_key):
    """A Resource_Manager acting as the test key, for live-test setup/teardown."""
    from eln_common.resourcemanage import Resource_Manager
    return Resource_Manager(key=api_key)


@pytest.fixture(autouse=True)
def slack_messages(monkeypatch):
    """Never let tests post to Slack; record what would have been sent."""
    import automations.slackbot as slackbot
    sent = []
    monkeypatch.setattr(
        slackbot, "send_message", lambda *args, **kwargs: sent.append((args, kwargs))
    )
    yield sent
