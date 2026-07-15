"""
Offline tests: routing, authentication plumbing, and request validation.
None of these need an eLN API key or network access.
"""

import json

import pytest

import web.search_process as search_process
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
