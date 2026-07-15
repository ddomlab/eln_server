"""
Offline tests: routing, authentication plumbing, and request validation.
None of these need an eLN API key or network access.
"""

import json
import threading

import pytest

import web.interface as interface
import web.search_process as search_process
from automations.labels.generate_label import LabelGenerator
from eln_common.fill_info import check_if_cas
from web.auth import get_key


class TestBasicRoutes:
    def test_ping(self, client):
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert resp.data == b"pong"

    def test_index_serves_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"<html" in resp.data.lower()

    def test_add_resource_interface(self, client):
        assert client.get("/add_resource_interface").status_code == 200

    def test_label_gen_interface(self, client):
        assert client.get("/label_gen_interface").status_code == 200

    def test_404_handler_reports_path(self, client):
        resp = client.get("/definitely_not_a_route")
        assert resp.status_code == 404
        assert b"/definitely_not_a_route" in resp.data


class TestAuthKeyExtraction:
    def test_bare_authorization_header(self, flask_app):
        with flask_app.test_request_context(headers={"Authorization": "somekey"}):
            assert get_key() == "somekey"

    def test_bearer_prefix_stripped(self, flask_app):
        with flask_app.test_request_context(headers={"Authorization": "Bearer somekey"}):
            assert get_key() == "somekey"

    def test_cookie_fallback(self, flask_app):
        with flask_app.test_request_context(headers={"Cookie": "apiKey=cookiekey"}):
            assert get_key() == "cookiekey"

    def test_header_wins_over_cookie(self, flask_app):
        with flask_app.test_request_context(
            headers={"Authorization": "headerkey", "Cookie": "apiKey=cookiekey"}
        ):
            assert get_key() == "headerkey"

    def test_missing_key_raises(self, flask_app):
        with flask_app.test_request_context():
            with pytest.raises(ValueError):
                get_key()


class TestAutomationApiAuth:
    def test_autofill_requires_key(self, client):
        resp = client.post("/api/autofill", json={})
        assert resp.status_code == 401
        assert resp.get_json()["status"] == "error"

    def test_check_peroxides_requires_key(self, client):
        resp = client.post("/api/check_peroxides")
        assert resp.status_code == 401
        assert resp.get_json()["status"] == "error"


class TestInputValidation:
    """Routes that validate the body before ever touching the eLN."""

    @pytest.mark.parametrize(
        "route", ["/print", "/mark_open", "/mark_empty", "/change_location", "/associate"]
    )
    def test_empty_id_list_rejected(self, client, route):
        resp = client.post(route, json={"id": []})
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_template_without_category_returns_empty(self, client):
        resp = client.get("/template")
        assert resp.status_code == 200
        assert resp.get_json() == {}

    def test_template_without_key_errors(self, client):
        resp = client.get("/template?category=2")
        assert resp.status_code == 400

    def test_get_locations_without_key_errors(self, client):
        resp = client.get("/get_locations")
        assert resp.status_code == 400

    def test_add_resource_non_object_body_rejected(self, client):
        resp = client.post("/add_resource", json=[1, 2, 3])
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_add_resource_missing_fields_rejected(self, client):
        resp = client.post("/add_resource", json={"title": "no other fields"})
        assert resp.status_code == 400


class TestSearchProcessHelpers:
    TEMPLATE = {
        "title": "Water",
        "body": "<p>hi</p>",
        "category": 2,
        "extra_fields": {"CAS": {"type": "text", "value": "7732-18-5"}},
    }

    def test_dict_complexify(self):
        complexed = search_process.dict_complexify(self.TEMPLATE)
        assert complexed["title"] == "Water"
        assert complexed["category"] == 2
        assert json.loads(complexed["metadata"])["extra_fields"] == self.TEMPLATE["extra_fields"]

    def test_simplify_inverts_complexify(self):
        simplified = search_process.dict_simplify(search_process.dict_complexify(self.TEMPLATE))
        assert simplified == {
            "title": "Water",
            "extra_fields": self.TEMPLATE["extra_fields"],
        }


class TestCasValidation:
    @pytest.mark.parametrize("cas", ["7732-18-5", "50-00-0", "1234567-89-1"])
    def test_valid_cas(self, cas):
        assert check_if_cas(cas)

    @pytest.mark.parametrize(
        "not_cas", ["", "water", "7732-18", "7732-185-5", "7732-18-55", "a-bc-d", "7-73-2"]
    )
    def test_invalid_cas(self, not_cas):
        assert not check_if_cas(not_cas)


class TestConfig:
    def test_config_yaml_values_are_loaded(self):
        """config.yaml at the repo root is the source of settings; check that it
        parses and that config.py exposes it with the expected types/resolution."""
        import eln_common.config as config

        assert config.URL.startswith("http")
        assert isinstance(config.AUTO_UPLOAD_LABELS, bool)
        # configured paths are absolute after repo-root resolution
        assert config.PRINTER_PATH.startswith("/")

    def test_relative_paths_resolve_from_repo_root(self):
        import eln_common.config as config

        assert config._path("eln_common/api_key") == str(
            config.PROJECT_ROOT / "eln_common" / "api_key"
        )
        assert config._path("/tmp/label.pdf") == "/tmp/label.pdf"


class TestSecrets:
    def test_get_secret_reads_field(self, monkeypatch, tmp_path):
        import eln_common.config as config

        secrets = tmp_path / "secrets.yaml"
        secrets.write_text('eln_api_key: "abc123"\nslack_bot_token: ""\n')
        monkeypatch.setattr(config, "SECRETS_PATH", secrets)
        assert config.get_secret("eln_api_key") == "abc123"
        # empty string means "not filled in"
        assert config.get_secret("slack_bot_token") is None
        assert config.get_secret("nonexistent") is None

    def test_get_secret_missing_file_returns_none(self, monkeypatch, tmp_path):
        import eln_common.config as config

        monkeypatch.setattr(config, "SECRETS_PATH", tmp_path / "nope.yaml")
        assert config.get_secret("eln_api_key") is None

    def test_get_api_key_without_secret_raises(self, monkeypatch, tmp_path):
        import eln_common.config as config

        monkeypatch.setattr(config, "SECRETS_PATH", tmp_path / "nope.yaml")
        with pytest.raises(ValueError, match="eln_api_key"):
            config.get_api_key()

    def test_slack_token_missing_raises_helpful_error(self, monkeypatch, tmp_path):
        import automations.slackbot as slackbot
        import eln_common.config as config

        monkeypatch.setattr(config, "SECRETS_PATH", tmp_path / "nope.yaml")
        with pytest.raises(ValueError, match="slack_bot_token"):
            slackbot._get_token()

    def test_example_file_has_the_expected_fields(self):
        import yaml

        from eln_common.config import PROJECT_ROOT

        example = yaml.safe_load((PROJECT_ROOT / "secrets.example.yaml").read_text())
        assert set(example) == {"eln_api_key", "slack_bot_token"}


class FakeRM:
    """Minimal Resource_Manager stand-in for label/creation tests."""

    printer_path = "/tmp/label.pdf"

    def __init__(self, item: dict | None = None, create_id: int = 999):
        self.item = item
        self.create_id = create_id
        self.created = []

    def get_item(self, id):
        return self.item

    def create_item(self, category, body):
        self.created.append((category, body))
        return self.create_id


class TestLabelGenerator:
    def test_missing_received_field_leaves_date_blank(self):
        rm = FakeRM(item={
            "id": 393,
            "title": "No received date",
            "category": 2,
            "metadata": json.dumps({"extra_fields": {}}),
        })
        gen = LabelGenerator(rm)  # type: ignore[arg-type]
        gen.add_item(393)
        assert gen.records[0]["received_date"] == ""

    def test_null_metadata_leaves_date_blank(self):
        rm = FakeRM(item={"id": 393, "title": "t", "category": 2, "metadata": None})
        gen = LabelGenerator(rm)  # type: ignore[arg-type]
        gen.add_item(393)
        assert gen.records[0]["received_date"] == ""


class TestAddResourceAutofill:
    def test_add_resource_triggers_background_autofill(self, client, monkeypatch):
        fake_rm = FakeRM(create_id=999)
        monkeypatch.setattr(interface, "rm", lambda: fake_rm)

        autofilled = threading.Event()
        autofill_calls = []

        def fake_autofill_item(rmn, item_id, **kwargs):
            autofill_calls.append(item_id)
            autofilled.set()

        monkeypatch.setattr(interface.autofill, "autofill_item", fake_autofill_item)

        resp = client.post("/add_resource", json={
            "title": "new thing",
            "body": "",
            "category": 2,
            "extra_fields": {},
        })
        assert resp.status_code == 200
        assert resp.get_json() == {
            "status": "ok",
            "received": {"title": "new thing", "body": "", "category": 2, "extra_fields": {}},
            "id": 999,
        }
        assert fake_rm.created[0][0] == 2
        # the autofill runs on a background thread right after creation
        assert autofilled.wait(timeout=2), "autofill was not triggered by /add_resource"
        assert autofill_calls == [999]


class TestCreateLabel:
    def test_create_label_returns_pdf(self, client):
        resp = client.post(
            "/create_label",
            json={
                "Title": "pytest label",
                "Text": "generated by the test suite",
                "Icon": "None",
                "QRContentType": "Resource",
                "QRContent": 393,
                "Height": 18,
            },
        )
        assert resp.status_code == 200
        assert resp.data.startswith(b"%PDF")
