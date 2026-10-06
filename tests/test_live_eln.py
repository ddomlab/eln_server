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

        # marking an already-opened item is reported, not changed
        resp = client.post("/mark_open", json={"id": [TEST_ITEM_ID]}, headers=auth_headers)
        assert resp.status_code == 200
        assert "already marked open" in resp.get_json()["problems"][0]

    def test_move_to_storage_and_back(self, client, auth_headers, live_rm):
        containers = get_item_raw(live_rm).get("containers") or []
        if len(containers) != 1:
            pytest.skip(f"Item {TEST_ITEM_ID} needs exactly one storage entry")
        start = containers[0]["storage_id"]
        other = next(u["id"] for u in live_rm.get_storage_units()
                     if u.get("parent_id") is not None and u["id"] != start)
        try:
            resp = client.post("/move_to_storage", json={"id": [TEST_ITEM_ID], "storage_id": other},
                               headers=auth_headers)
            assert resp.status_code == 200 and resp.get_json()["moved"] == [TEST_ITEM_ID]
            assert get_item_raw(live_rm)["containers"][0]["storage_id"] == other
        finally:
            live_rm.move_container(TEST_ITEM_ID, containers[0]["id"], start)

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
