"""
Offline tests: routing, authentication plumbing, and request validation.
None of these need an eLN API key or network access.
"""

import json
from types import SimpleNamespace

import pytest

import eln_common.compound_import as compound_import
import eln_common.pubchem as pubchem
import web.interface as interface
import web.search_process as search_process
from automations.labels.generate_label import LabelGenerator
from eln_common.fill_info import check_if_cas
from eln_common.resourcemanage import Resource_Manager
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

    def test_settings_interface(self, client):
        assert client.get("/settings_interface").status_code == 200

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
    def test_autofill_route_is_gone(self, client):
        # removed 2026-10; the old timer must not find a working endpoint
        assert client.post("/api/autofill", json={}).status_code == 404

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

    @pytest.mark.parametrize(
        "body",
        [
            {"field": "Location", "option": "Shelf 9"},  # no category
            {"category": "x", "field": "Location", "option": "Shelf 9"},
            {"category": 2, "option": "Shelf 9"},  # no field
            {"category": 2, "field": "Location"},  # no option
            {"category": 2, "field": "Location", "option": "   "},
        ],
    )
    def test_add_option_invalid_body_rejected(self, client, body):
        resp = client.post("/add_option", json=body)
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_add_option_without_key_errors(self, client):
        resp = client.post(
            "/add_option", json={"category": 2, "field": "Location", "option": "Shelf 9"}
        )
        assert resp.status_code == 401


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
        # configured paths are absolute after repo-root resolution
        assert config.PRINTER_PATH.startswith("/")

    def test_relative_paths_resolve_from_repo_root(self):
        import eln_common.config as config

        assert config._path("eln_common/api_key") == str(
            config.PROJECT_ROOT / "eln_common" / "api_key"
        )
        assert config._path("/tmp/label.pdf") == "/tmp/label.pdf"

    def test_urls_are_required(self, monkeypatch):
        """The instance URLs have no lab-agnostic default; an unset key errors."""
        import eln_common.config as config

        monkeypatch.setattr(config, "_cfg", {})
        with pytest.raises(ValueError, match="eln_url"):
            config._require("eln_url")
        with pytest.raises(ValueError, match="eln_web_url"):
            config._require("eln_web_url")

    def test_item_web_url(self):
        import eln_common.config as config

        assert config.item_web_url(393) == f"{config.WEB_URL}/database.php?mode=view&id=393"
        assert not config.WEB_URL.endswith("/")

    def test_eln_config_endpoint_serves_web_url(self, client):
        import eln_common.config as config

        resp = client.get("/eln_config")
        assert resp.status_code == 200
        assert resp.get_json() == {"eln_web_url": config.WEB_URL}


class TestTeamIdSettings:
    """The team-specific status/category IDs configured in config.yaml."""

    def test_update_settings_rewrites_values_and_keeps_comments(self, monkeypatch, tmp_path):
        import eln_common.config as config

        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "# a load-bearing comment\n"
            "status_open: 4\n"
            "chemical_categories: [2, 3]\n"
        )
        monkeypatch.setattr(config, "CONFIG_PATH", cfg)

        config.update_settings({"status_open": 7, "chemical_categories": [5], "status_empty": 9})
        text = cfg.read_text()
        assert "# a load-bearing comment" in text
        assert "status_open: 7" in text
        assert "chemical_categories: [5]" in text
        assert "status_empty: 9" in text  # missing keys get appended

        # setting() re-reads the file, so the new values are immediately visible
        assert config.setting("status_open", 4) == 7
        assert config.setting("chemical_categories", []) == [5]
        assert config.setting("not_a_key", "fallback") == "fallback"

    def test_get_settings_endpoint(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        settings = resp.get_json()
        assert set(settings) == {
            "status_open", "status_empty", "chemical_categories", "label_date_categories"
        }
        assert isinstance(settings["status_open"], int)
        assert isinstance(settings["chemical_categories"], list)

    def test_post_settings_requires_key(self, client):
        resp = client.post("/settings", json={"status_open": 4})
        assert resp.status_code == 401

    @pytest.mark.parametrize("route", ["/categories", "/statuses"])
    def test_list_endpoints_require_key(self, client, route):
        resp = client.get(route)
        assert resp.status_code == 401


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


class TestAddResource:
    def test_add_resource_creates_item_from_template(self, client, monkeypatch):
        fake_rm = FakeRM(create_id=999)
        monkeypatch.setattr(interface, "rm", lambda: fake_rm)
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


class TestLookupLists:
    """The add-resource page loads existing compounds and storage places into dropdowns."""

    def test_compounds_list_is_trimmed_and_sorted(self, client, monkeypatch):
        fake_rm = SimpleNamespace(get_compounds=lambda: [
            {"id": 72, "name": "acetone", "cas_number": "67-64-1", "molecular_formula": "C3H6O", "smiles": "CC(C)=O"},
            {"id": 111, "name": "Chlorobenzene", "cas_number": "108-90-7", "molecular_formula": None},
            {"id": 196, "name": None, "cas_number": None, "molecular_formula": None},
        ])
        monkeypatch.setattr(interface, "rm", lambda: fake_rm)
        resp = client.get("/compounds_list")
        assert resp.status_code == 200
        assert resp.get_json() == [
            {"id": 196, "name": "", "cas": "", "formula": ""},
            {"id": 72, "name": "acetone", "cas": "67-64-1", "formula": "C3H6O"},
            {"id": 111, "name": "Chlorobenzene", "cas": "108-90-7", "formula": ""},
        ]

    def test_storage_tree_keeps_hierarchy(self, client, monkeypatch):
        fake_rm = SimpleNamespace(get_storage_units=lambda: [
            {"id": 4, "name": "Room 3057", "parent_id": None, "full_path": "Room 3057", "level_depth": 0},
            {"id": 5, "name": "Front hood", "parent_id": 4, "full_path": "Room 3057 > Front hood", "level_depth": 1},
        ])
        monkeypatch.setattr(interface, "rm", lambda: fake_rm)
        resp = client.get("/storage_tree")
        assert resp.status_code == 200
        assert resp.get_json() == [
            {"id": 4, "name": "Room 3057", "parent_id": None, "full_path": "Room 3057"},
            {"id": 5, "name": "Front hood", "parent_id": 4, "full_path": "Room 3057 > Front hood"},
        ]

    @pytest.mark.parametrize("path", ["/compounds_list", "/storage_tree"])
    def test_lists_need_an_api_key(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 401


class FakeCompoundRM:
    """Stand-in for the compound calls of Resource_Manager."""

    def __init__(self, compounds, create_returns=200):
        self.compounds = compounds
        self.create_returns = create_returns
        self.created, self.patched = [], []

    def get_all_compounds(self):
        return self.compounds

    def create_compound(self, body):
        self.created.append(body)
        return self.create_returns

    def patch_compound(self, id, body):
        self.patched.append((id, body))

    def get_compound(self, id):
        patches = [b for i, b in self.patched if i == id and "name" in b]
        body = patches[-1] if patches else self.created[-1]
        return {"id": id, "name": body.get("name"), "cas_number": body.get("cas_number"),
                "molecular_formula": body.get("molecular_formula"), "state": 1}


# what eln_common.pubchem.fetch returns
MANNITOL = {"pubchem_cid": 6251, "cas_number": "87-78-5", "name": "Mannitol",
            "inchi_key": "FBPFZTCFMRRESA-KVTDHHQDSA-N", "molecular_formula": "C6H14O6",
            "molecular_weight": 182.17, "smiles": "C(...)O", "iupac_name": None, "pictograms": []}
THF = {"pubchem_cid": 8028, "cas_number": "109-99-9", "name": "Tetrahydrofuran",
       "inchi_key": "WYURNTSHIVDZCO-UHFFFAOYSA-N", "molecular_formula": "C4H8O",
       "molecular_weight": 72.11, "smiles": "C1CCOC1", "pictograms": ["GHS02", "GHS07", "GHS08"]}
PHENYLBORONIC = {"pubchem_cid": 66827, "cas_number": "98-80-6", "name": "Phenylboronic Acid",
                 "inchi_key": "HXITXNWTGFUOAU-UHFFFAOYSA-N", "molecular_formula": "C6H7BO2",
                 "molecular_weight": 121.93, "pictograms": ["GHS07"]}
PHENYLBORONIC_8_DELETED = {"id": 8, "name": "Phenylboronic acid", "cas_number": "98-80-6", "state": 3}
HEXITOL_80 = {"id": 80, "name": "Hexitol", "cas_number": "87-78-5", "pubchem_cid": 453,
              "inchi_key": "FBPFZTCFMRRESA-UHFFFAOYSA-N", "state": 1}


class TestCompoundImport:
    """Rules from the 2026-09 cleanup: eLabFTW overwrites a compound that shares a
    unique field, even a deleted one, so clashes are refused before creating."""

    def test_users_cas_is_kept_and_pubchems_cas_does_not_clash(self):
        # Mannitol: the bottle says 69-65-8, PubChem lists 87-78-5 which Hexitol (#80) holds
        rm = FakeCompoundRM([HEXITOL_80], create_returns=126)
        created = compound_import.create_compound_safely(rm, MANNITOL, "69-65-8")
        assert created["id"] == 126 and created["cas_number"] == "69-65-8"
        assert rm.created[0]["pubchem_cid"] == 6251
        assert rm.patched == [(126, {"molecular_weight": 182.17})]
        # empty fields are left out, and no pictograms means no hazard flags
        assert "iupac_name" not in rm.created[0]
        assert not any(k.startswith("is_") for k in rm.created[0])

    def test_pictograms_turn_on_hazard_flags(self):
        rm = FakeCompoundRM([], create_returns=127)
        compound_import.create_compound_safely(rm, THF, None)
        flags = {k: v for k, v in rm.created[0].items() if k.startswith("is_")}
        assert flags == {"is_flammable": 1, "is_hazardous2health": 1, "is_serious_health_hazard": 1}
        assert rm.created[0]["cas_number"] == "109-99-9"
        assert "pictograms" not in rm.created[0]

    def test_unknown_hazards_set_no_flags(self):
        # pictograms None: PubChem has no GHS classification
        rm = FakeCompoundRM([], create_returns=128)
        compound_import.create_compound_safely(rm, {**THF, "pictograms": None}, None)
        assert not any(k.startswith("is_") for k in rm.created[0])

    def test_same_pubchem_id_is_refused(self):
        existing = {**HEXITOL_80, "pubchem_cid": 6251}
        rm = FakeCompoundRM([existing])
        with pytest.raises(compound_import.CompoundClash) as e:
            compound_import.create_compound_safely(rm, MANNITOL, "69-65-8")
        assert e.value.existing["id"] == 80 and "PubChem ID" in e.value.reason
        assert rm.created == []

    def test_deleted_compound_with_same_cas_is_refused_but_can_be_restored(self):
        # like #8 Phenylboronic acid: deleted, but it still holds its CAS
        rm = FakeCompoundRM([PHENYLBORONIC_8_DELETED])
        with pytest.raises(compound_import.CompoundClash) as e:
            compound_import.create_compound_safely(rm, PHENYLBORONIC, "98-80-6")
        assert e.value.existing["id"] == 8 and compound_import.summary(e.value.existing)["deleted"]
        assert e.value.can_restore and rm.created == [] and rm.patched == []

    def test_restore_refreshes_the_deleted_compound(self):
        rm = FakeCompoundRM([PHENYLBORONIC_8_DELETED])
        restored = compound_import.create_compound_safely(rm, PHENYLBORONIC, "98-80-6", restore_id=8)
        assert restored["id"] == 8 and rm.created == []
        [(patched_id, body)] = rm.patched
        assert patched_id == 8
        assert body["name"] == "Phenylboronic Acid" and body["cas_number"] == "98-80-6"
        assert body["molecular_weight"] == 121.93
        # every hazard flag is written, as "on"/"off" (what eLabFTW's PATCH reads)
        assert body["is_hazardous2health"] == "on" and body["is_flammable"] == "off"
        assert len([k for k in body if k.startswith("is_")]) == 9
        assert list(body)[-1] == "state" and body["state"] == 1

    def test_restore_keeps_flags_when_hazards_are_unknown(self):
        rm = FakeCompoundRM([PHENYLBORONIC_8_DELETED])
        compound_import.create_compound_safely(rm, {**PHENYLBORONIC, "pictograms": None}, "98-80-6", restore_id=8)
        assert not any(k.startswith("is_") for k in rm.patched[0][1])

    def test_restore_needs_the_matching_id(self):
        rm = FakeCompoundRM([PHENYLBORONIC_8_DELETED])
        with pytest.raises(compound_import.CompoundClash):
            compound_import.create_compound_safely(rm, PHENYLBORONIC, "98-80-6", restore_id=9)
        assert rm.patched == []

    def test_live_match_wins_over_deleted_and_cannot_be_restored(self):
        live = {"id": 30, "name": "Phenylboronic acid (2)", "pubchem_cid": 66827, "state": 1}
        rm = FakeCompoundRM([PHENYLBORONIC_8_DELETED, live])
        with pytest.raises(compound_import.CompoundClash) as e:
            compound_import.create_compound_safely(rm, PHENYLBORONIC, "98-80-6", restore_id=8)
        assert e.value.existing["id"] == 30 and not e.value.can_restore
        assert rm.patched == []

    def test_two_deleted_matches_cannot_be_restored(self):
        other = {"id": 9, "name": "old copy", "pubchem_cid": 66827, "state": 3}
        clash = compound_import.find_clash(PHENYLBORONIC, "98-80-6", [PHENYLBORONIC_8_DELETED, other])
        assert clash and not clash.can_restore

    def test_existing_id_returned_by_elabftw_stops(self):
        # if eLabFTW still overwrote something, never treat that compound as new
        rm = FakeCompoundRM([HEXITOL_80], create_returns=80)
        with pytest.raises(RuntimeError, match="#80"):
            compound_import.create_compound_safely(rm, MANNITOL, "69-65-8")
        assert rm.patched == []


class FakePubChem:
    """Stand-in for requests in eln_common.pubchem: answers by URL, 404 for anything unknown."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def _answer(self, url, **kwargs):
        self.calls.append((url, kwargs))
        for part, body in self.answers.items():
            if part in url:
                return SimpleNamespace(status_code=200, json=lambda body=body: body,
                                       raise_for_status=lambda: None)
        return SimpleNamespace(status_code=404)

    get = post = _answer


def ghs_answer(*sources):
    """A PubChem GHS Classification record; each source is a list of pictogram codes."""
    info = []
    for codes in sources:
        info.append({"Name": "Pictogram(s)", "Value": {"StringWithMarkup": [{"String": "", "Markup": [
            {"URL": f"https://pubchem.ncbi.nlm.nih.gov/images/ghs/{c}.svg", "Type": "Icon"}
            for c in codes]}]}})
        info.append({"Name": "Signal", "Value": {"StringWithMarkup": [{"String": "Danger"}]}})
    section = {"TOCHeading": "GHS Classification", "Information": info}
    return {"Record": {"Section": [{"TOCHeading": "Safety and Hazards", "Section": [
        {"TOCHeading": "Hazards Identification", "Section": [section]}]}]}}


THF_PROPERTIES = {"PropertyTable": {"Properties": [{
    "CID": 8028, "Title": "Tetrahydrofuran", "IUPACName": "oxolane", "MolecularFormula": "C4H8O",
    "MolecularWeight": "72.11", "SMILES": "C1CCOC1", "InChI": "InChI=1S/C4H8O/c1-2-4-5-3-1/h1-4H2",
    "InChIKey": "WYURNTSHIVDZCO-UHFFFAOYSA-N"}]}}
THF_SYNONYMS = {"InformationList": {"Information": [
    {"CID": 8028, "Synonym": ["tetrahydrofuran", "THF", "109-99-9", "oxolane", "1-23-4567"]}]}}


class TestPubChem:
    """eln_common.pubchem with PubChem's answers faked (shapes copied from real ones)."""

    def test_pictograms_from_all_sources_are_combined(self, monkeypatch):
        fake = FakePubChem({"/pug_view/data/compound/8028/": ghs_answer(["GHS02", "GHS07", "GHS08"], ["GHS07"])})
        monkeypatch.setattr(pubchem, "requests", fake)
        assert pubchem.ghs_pictograms(8028) == ["GHS02", "GHS07", "GHS08"]
        assert fake.calls[0][1]["params"] == {"heading": "GHS Classification"}

    def test_classified_without_pictograms_is_empty_list(self, monkeypatch):
        # like glucose: PubChem has a GHS section but no source gives a pictogram
        monkeypatch.setattr(pubchem, "requests", FakePubChem({"/pug_view/": ghs_answer()}))
        assert pubchem.ghs_pictograms(5793) == []

    def test_no_classification_is_none(self, monkeypatch):
        monkeypatch.setattr(pubchem, "requests", FakePubChem({}))
        assert pubchem.ghs_pictograms(24857) is None

    def test_fetch_uses_elabftw_field_names(self, monkeypatch):
        monkeypatch.setattr(pubchem, "requests", FakePubChem({
            "/cid/8028/property/": THF_PROPERTIES,
            "/cid/8028/synonyms/": THF_SYNONYMS,
            "/pug_view/data/compound/8028/": ghs_answer(["GHS02", "GHS07", "GHS08"]),
        }))
        assert pubchem.fetch(8028) == {
            "pubchem_cid": 8028, "name": "Tetrahydrofuran", "iupac_name": "oxolane",
            "molecular_formula": "C4H8O", "molecular_weight": 72.11, "smiles": "C1CCOC1",
            "inchi": "InChI=1S/C4H8O/c1-2-4-5-3-1/h1-4H2", "inchi_key": "WYURNTSHIVDZCO-UHFFFAOYSA-N",
            "cas_number": "109-99-9", "pictograms": ["GHS02", "GHS07", "GHS08"],
        }

    def test_fetch_unknown_cid_is_none(self, monkeypatch):
        monkeypatch.setattr(pubchem, "requests", FakePubChem({}))
        assert pubchem.fetch(999999999) is None

    def test_search_by_cas_keeps_the_cas_and_sends_it_as_form_data(self, monkeypatch):
        fake = FakePubChem({"/compound/name/property/": THF_PROPERTIES})
        monkeypatch.setattr(pubchem, "requests", fake)
        found = pubchem.search(cas="109-99-9")
        assert [(c["pubchem_cid"], c["cas_number"]) for c in found] == [(8028, "109-99-9")]
        assert fake.calls[0][1]["data"] == {"name": "109-99-9"}
        assert len(fake.calls) == 1  # no synonyms call needed

    def test_search_by_name_finds_the_cas_in_synonyms(self, monkeypatch):
        monkeypatch.setattr(pubchem, "requests", FakePubChem({
            "/compound/name/property/": THF_PROPERTIES, "/cid/8028/synonyms/": THF_SYNONYMS}))
        assert pubchem.search(name="THF")[0]["cas_number"] == "109-99-9"

    def test_search_without_match_is_empty(self, monkeypatch):
        monkeypatch.setattr(pubchem, "requests", FakePubChem({}))
        assert pubchem.search(cas="1599466-85-9") == []


class TestCompoundRoutes:
    def test_preview_marks_existing_compound(self, client, monkeypatch):
        acetone = {"pubchem_cid": 180, "cas_number": "67-64-1", "name": "Acetone", "molecular_formula": "C3H6O"}
        rm = FakeCompoundRM([{"id": 72, "name": "Acetone", "cas_number": "67-64-1", "pubchem_cid": 180,
                              "molecular_formula": "C3H6O", "state": 1}])
        monkeypatch.setattr(interface, "rm", lambda: rm)
        monkeypatch.setattr(pubchem, "search", lambda cas=None, name=None: [acetone])
        resp = client.get("/compounds/pubchem?cas=67-64-1")
        assert resp.status_code == 200
        candidate = resp.get_json()["candidates"][0]
        assert candidate["pubchem"]["name"] == "Acetone" and candidate["pubchem"]["cid"] == 180
        assert candidate["existing"]["id"] == 72 and candidate["reason"] == "same PubChem ID"
        assert candidate["can_restore"] is False

    def test_preview_not_in_pubchem_is_404(self, client, monkeypatch):
        monkeypatch.setattr(interface, "rm", lambda: FakeCompoundRM([]))
        monkeypatch.setattr(pubchem, "search", lambda cas=None, name=None: [])
        assert client.get("/compounds/pubchem?cas=1599466-85-9").status_code == 404

    def test_preview_needs_cas_or_name(self, client):
        assert client.get("/compounds/pubchem").status_code == 400

    def test_create_returns_201_with_new_compound(self, client, monkeypatch):
        rm = FakeCompoundRM([HEXITOL_80], create_returns=126)
        monkeypatch.setattr(interface, "rm", lambda: rm)
        monkeypatch.setattr(pubchem, "fetch", lambda cid: MANNITOL)
        resp = client.post("/compounds", json={"cid": 6251, "cas": "69-65-8"})
        assert resp.status_code == 201
        assert resp.get_json() == {"id": 126, "name": "Mannitol", "cas": "69-65-8", "formula": "C6H14O6",
                                   "deleted": False, "restored": False, "pictograms": []}

    def test_create_reports_pictograms(self, client, monkeypatch):
        monkeypatch.setattr(interface, "rm", lambda: FakeCompoundRM([], create_returns=127))
        monkeypatch.setattr(pubchem, "fetch", lambda cid: THF)
        resp = client.post("/compounds", json={"cid": 8028})
        assert resp.status_code == 201
        assert resp.get_json()["pictograms"] == ["GHS02", "GHS07", "GHS08"]

    def test_create_unknown_hazards_is_null(self, client, monkeypatch):
        monkeypatch.setattr(interface, "rm", lambda: FakeCompoundRM([], create_returns=128))
        monkeypatch.setattr(pubchem, "fetch", lambda cid: {**THF, "pictograms": None})
        assert client.post("/compounds", json={"cid": 8028}).get_json()["pictograms"] is None

    def test_create_clash_is_409_with_existing(self, client, monkeypatch):
        rm = FakeCompoundRM([{**HEXITOL_80, "pubchem_cid": 6251}])
        monkeypatch.setattr(interface, "rm", lambda: rm)
        monkeypatch.setattr(pubchem, "fetch", lambda cid: MANNITOL)
        resp = client.post("/compounds", json={"cid": 6251, "cas": "69-65-8"})
        assert resp.status_code == 409
        assert resp.get_json()["existing"]["id"] == 80 and resp.get_json()["can_restore"] is False

    def test_create_deleted_match_offers_restore_then_restores(self, client, monkeypatch):
        rm = FakeCompoundRM([PHENYLBORONIC_8_DELETED])
        monkeypatch.setattr(interface, "rm", lambda: rm)
        monkeypatch.setattr(pubchem, "fetch", lambda cid: PHENYLBORONIC)
        resp = client.post("/compounds", json={"cid": 66827, "cas": "98-80-6"})
        assert resp.status_code == 409 and resp.get_json()["can_restore"] is True
        resp = client.post("/compounds", json={"cid": 66827, "cas": "98-80-6", "restore": 8})
        assert resp.status_code == 200
        assert resp.get_json()["id"] == 8 and resp.get_json()["restored"] is True

    def test_create_cid_not_in_pubchem_is_404(self, client, monkeypatch):
        monkeypatch.setattr(interface, "rm", lambda: FakeCompoundRM([]))
        monkeypatch.setattr(pubchem, "fetch", lambda cid: None)
        assert client.post("/compounds", json={"cid": 999999999}).status_code == 404

    @pytest.mark.parametrize("body", [{}, {"cid": "abc"}, {"cid": 6251, "cas": "not-a-cas"},
                                      {"cid": 6251, "restore": "8"}, {"cid": 6251, "restore": True}])
    def test_create_rejects_bad_input(self, client, body):
        assert client.post("/compounds", json=body).status_code == 400


class TestCreateItemFromTemplate:
    """New resources start from their template, so they get its category and
    default status (items created from a bare category had no status)."""

    def test_posts_template_and_patches_the_rest(self):
        posted, patched = [], []
        rm = Resource_Manager.__new__(Resource_Manager)  # skip the API-key setup
        rm.itemsapi = SimpleNamespace(post_item_with_http_info=lambda body: (
            posted.append(body) or (None, 201, {"Location": "https://eln/api/v2/items/615"})))
        rm.change_item = lambda id, body: patched.append((id, body))

        body = {"title": "Sudan I", "body": "", "category": 2, "metadata": "{}"}
        assert rm.create_item(2, body) == 615
        assert posted == [{"template": 2}]
        # category comes from the template, so it isn't patched over
        assert patched == [(615, {"title": "Sudan I", "body": "", "metadata": "{}"})]


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
