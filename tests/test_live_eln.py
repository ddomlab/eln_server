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

    def test_template_endpoint(self, client, auth_headers, live_rm):
        category = int(live_rm.get_item(TEST_ITEM_ID)["category"])
        resp = client.get(f"/template?category={category}", headers=auth_headers)
        assert resp.status_code == 200
        template = resp.get_json()
        assert int(template["id"]) == category
        assert "metadata" in template

    def test_get_locations(self, client, auth_headers):
        resp = client.get("/get_locations", headers=auth_headers)
        assert resp.status_code == 200
        locations = resp.get_json()
        assert isinstance(locations, list)

    def test_template_with_garbage_key_errors(self, client):
        resp = client.get(
            "/template?category=2", headers={"Authorization": "not-a-real-key"}
        )
        assert resp.status_code == 400


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
    def test_print_merges_uploaded_label(self, client, auth_headers, live_rm):
        """Exercises the uploads read path (read_uploads + read_upload binary)."""
        names = [f.to_dict()["real_name"] for f in live_rm.get_uploaded_files(TEST_ITEM_ID)]
        if "label.pdf" not in names:
            pytest.skip(f"Item {TEST_ITEM_ID} has no uploaded label.pdf")
        resp = client.post("/print", json={"id": [TEST_ITEM_ID]}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.data.startswith(b"%PDF")


class TestAutomationApi:
    def test_autofill_single_item(self, client, auth_headers, slack_messages):
        """Default autofill on 393: idempotent when the item is already filled
        (existing label is kept, 'Autofilled' tag short-circuits info/image)."""
        resp = client.post("/api/autofill", json={"id": TEST_ITEM_ID}, headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json() == {"status": "ok"}
        assert slack_messages == []  # no error reports

    def test_autofill_bad_key_reports_error(self, client, slack_messages):
        resp = client.post(
            "/api/autofill",
            json={"id": TEST_ITEM_ID},
            headers={"Authorization": "not-a-real-key"},
        )
        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"
        assert len(slack_messages) == 1  # failure went to the (stubbed) error channel


class TestSearch:
    TEMPLATE = {
        "title": "",
        "body": "",
        "category": 2,
        "extra_fields": {
            "Full name": {"type": "text", "value": ""},
            "CAS": {"type": "text", "value": ""},
        },
    }

    def test_search_by_cas_fills_fields(self, client):
        resp = client.post(
            "/search", json={"CAS": "7732-18-5", "template": self.TEMPLATE}
        )
        assert resp.status_code == 200
        result = resp.get_json()
        fields = result["extra_fields"]
        assert fields["CAS"]["value"] == "7732-18-5"
        assert "pubchem" in fields["Pubchem Link"]["value"].lower()
        assert float(fields["Molecular Weight"]["value"]) == pytest.approx(18.015, abs=0.1)
        assert result["title"].lower() == "water"

    @pytest.mark.xfail(
        reason="pubchempy cannot read SMILES from the current PubChem schema; "
        "fill_info falls back to 'PubChem Error, could not fetch SMILES'",
        strict=False,
    )
    def test_search_fills_smiles(self, client):
        resp = client.post(
            "/search", json={"CAS": "7732-18-5", "template": self.TEMPLATE}
        )
        assert resp.status_code == 200
        assert resp.get_json()["extra_fields"]["SMILES"]["value"] == "O"

    def test_search_unknown_compound_is_400(self, client):
        resp = client.post(
            "/search", json={"CAS": "0000000-99-9", "template": self.TEMPLATE}
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()
