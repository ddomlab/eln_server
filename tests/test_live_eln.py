"""
Live tests against the real eLabFTW server (and PubChem for /search).

All mutations are confined to resource TEST_ITEM_ID (393) and restore the
item's original metadata/status afterwards. /api/check_peroxides is
deliberately untested beyond its auth check (offline suite): a successful run
would send real reminders for every match in the inventory.

Run only these with:   pytest -m live
Skip them with:        pytest -m "not live"
"""

import copy
import json
from datetime import datetime

import pytest

from tests.conftest import TEST_ITEM_ID

pytestmark = pytest.mark.live

STATUS_OPEN = 4
STATUS_EMPTY = 5


def get_item_raw(live_rm, item_id: int = TEST_ITEM_ID) -> dict:
    """Fetch the item as raw API JSON (metadata stays a JSON string) rather than
    through elabapi's models, whose to_dict() mangles metadata on 5.x."""
    return live_rm.get_url(f"/items/{item_id}").json()


@pytest.fixture()
def restore_item(live_rm):
    """Snapshot resource 393 before the test and restore metadata/status after."""
    original = get_item_raw(live_rm)
    assert original["id"] == TEST_ITEM_ID
    yield original
    body = {"metadata": original["metadata"]}
    if original.get("status") is not None:
        body["status"] = int(original["status"])
    live_rm.change_item(TEST_ITEM_ID, body)


class TestReads:
    def test_item_393_exists(self, live_rm):
        item = live_rm.get_item(TEST_ITEM_ID)
        assert item["id"] == TEST_ITEM_ID
        assert item["title"]

    def test_get_locations(self, client, auth_headers):
        resp = client.get("/get_locations", headers=auth_headers)
        assert resp.status_code == 200
        locations = resp.get_json()
        assert isinstance(locations, list)

    def test_categories_lists_team_categories(self, client, auth_headers):
        resp = client.get("/categories", headers=auth_headers)
        assert resp.status_code == 200
        categories = resp.get_json()
        assert all(set(c) == {"id", "title"} for c in categories)
        assert {"id": 2, "title": "Chemical Compound"} in categories

    def test_statuses_lists_team_statuses(self, client, auth_headers):
        resp = client.get("/statuses", headers=auth_headers)
        assert resp.status_code == 200
        statuses = resp.get_json()
        by_id = {s["id"]: s["title"] for s in statuses}
        # the DDOM defaults in config.yaml correspond to these
        assert by_id[4] == "Opened"
        assert by_id[5] == "Empty"

    def test_post_settings_updates_config_file(self, client, auth_headers, monkeypatch, tmp_path):
        """Round-trip through the settings endpoint against a copy of the real
        config.yaml so the actual file is never modified."""
        import eln_common.config as config

        cfg_copy = tmp_path / "config.yaml"
        cfg_copy.write_text(config.CONFIG_PATH.read_text())
        monkeypatch.setattr(config, "CONFIG_PATH", cfg_copy)

        resp = client.post(
            "/settings",
            json={"status_open": 4, "chemical_categories": [2, 3, 4], "ignored_key": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["updated"] == {"status_open": 4, "chemical_categories": [2, 3, 4]}
        assert config.setting("chemical_categories", []) == [2, 3, 4]
        assert "## Team-specific IDs" in cfg_copy.read_text()  # comments survive


class TestMutations:
    def test_mark_open_sets_date_and_rejects_reopen(
        self, client, auth_headers, live_rm, restore_item
    ):
        meta = json.loads(restore_item["metadata"])
        if "Opened" not in meta.get("extra_fields", {}):
            pytest.skip(f"Item {TEST_ITEM_ID} has no 'Opened' extra field")

        # start from a known un-opened state
        cleared = copy.deepcopy(meta)
        cleared["extra_fields"]["Opened"]["value"] = ""
        live_rm.change_item(TEST_ITEM_ID, {"metadata": json.dumps(cleared)})

        resp = client.post("/mark_open", json={"id": [TEST_ITEM_ID]}, headers=auth_headers)
        assert resp.status_code == 200

        updated = get_item_raw(live_rm)
        assert (
            json.loads(updated["metadata"])["extra_fields"]["Opened"]["value"]
            == datetime.now().isoformat()[:10]
        )
        assert int(updated["status"]) == STATUS_OPEN

        # marking an already-opened item must fail
        resp = client.post("/mark_open", json={"id": [TEST_ITEM_ID]}, headers=auth_headers)
        assert resp.status_code == 400
        assert "already marked" in resp.get_json()["error"]

    def test_change_location(self, client, auth_headers, live_rm, restore_item):
        meta = json.loads(restore_item["metadata"])
        if "Location" not in meta.get("extra_fields", {}):
            pytest.skip(f"Item {TEST_ITEM_ID} has no 'Location' extra field")

        resp = client.post(
            "/change_location",
            json={"id": [TEST_ITEM_ID], "location": "pytest test location"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        updated = json.loads(get_item_raw(live_rm)["metadata"])
        assert updated["extra_fields"]["Location"]["value"] == "pytest test location"

    def test_mark_empty(self, client, auth_headers, live_rm, restore_item):
        resp = client.post("/mark_empty", json={"id": [TEST_ITEM_ID]}, headers=auth_headers)
        assert resp.status_code == 200
        assert int(get_item_raw(live_rm)["status"]) == STATUS_EMPTY


class TestPrint:
    def test_print_generates_label_on_the_fly(self, client, auth_headers):
        """/print builds the label from the item's current data at request time;
        it does not depend on a label.pdf upload existing on the resource."""
        resp = client.post("/print", json={"id": [TEST_ITEM_ID]}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.data.startswith(b"%PDF")
