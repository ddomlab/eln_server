"""
Offline tests: routing, authentication plumbing, and request validation.
None of these need an eLN API key or network access.
"""

import json
from datetime import date
from types import SimpleNamespace

import pytest

import eln_common.add_bottle as add_bottle
import eln_common.bottle_actions as bottle_actions
import eln_common.bottle_tags as bottle_tags
import eln_common.routine_checks as routine_checks
import eln_common.compound_import as compound_import
import eln_common.pubchem as pubchem
import eln_common.storage_places as storage_places
import web.interface as interface
from automations.labels.generate_label import LabelGenerator
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

    def test_old_add_resource_page_redirects_to_the_new_one(self, client):
        resp = client.get("/add_resource_interface")
        assert resp.status_code == 302 and resp.headers["Location"].endswith("/add_bottle_interface")

    @pytest.mark.parametrize("route", ["/search", "/add_resource", "/add_option"])
    def test_old_add_routes_are_gone(self, client, route):
        assert client.post(route, json={}).status_code == 404

    def test_old_template_route_is_gone(self, client):
        assert client.get("/template?category=2").status_code == 404

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
        "route", ["/print", "/mark_open", "/mark_empty", "/move_to_storage", "/associate"]
    )
    def test_empty_id_list_rejected(self, client, route):
        resp = client.post(route, json={"id": []})
        assert resp.status_code == 400
        assert "error" in resp.get_json()

class TestCasValidation:
    @pytest.mark.parametrize("cas", ["7732-18-5", "50-00-0", "1234567-89-1"])
    def test_valid_cas(self, cas):
        assert pubchem.check_if_cas(cas)

    @pytest.mark.parametrize(
        "not_cas", ["", "water", "7732-18", "7732-185-5", "7732-18-55", "a-bc-d", "7-73-2"]
    )
    def test_invalid_cas(self, not_cas):
        assert not pubchem.check_if_cas(not_cas)


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
    """Minimal Resource_Manager stand-in for label tests."""

    printer_path = "/tmp/label.pdf"

    def __init__(self, item: dict | None = None):
        self.item = item

    def get_item(self, id):
        return self.item



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

    def test_pdf_is_made_in_memory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rm = FakeRM(item={"id": 624, "title": "Hydrogen peroxide 30%", "category": 2,
                          "metadata": json.dumps({"extra_fields": {"Received": {"value": "2026-10-05"}}})})
        gen = LabelGenerator(rm)  # type: ignore[arg-type]
        gen.add_item(624)
        assert gen.pdf().startswith(b"%PDF")
        assert gen.records == [] and list(tmp_path.iterdir()) == []

    def test_print_route_returns_pdf(self, client, monkeypatch):
        rm = FakeRM(item={"id": 624, "title": "t", "category": 2, "metadata": None})
        monkeypatch.setattr(interface, "rm", lambda: rm)
        resp = client.post("/print", json={"id": [624, "625"]})
        assert resp.status_code == 200 and resp.mimetype == "application/pdf"
        assert resp.data.startswith(b"%PDF")

    @pytest.mark.parametrize("body", [{"id": "624"}, {"id": ["abc"]}, {}])
    def test_print_bad_ids_are_400(self, client, body):
        assert client.post("/print", json=body).status_code == 400

    def test_print_needs_an_api_key(self, client):
        assert client.post("/print", json={"id": [624]}).status_code == 401

    def test_null_metadata_leaves_date_blank(self):
        rm = FakeRM(item={"id": 393, "title": "t", "category": 2, "metadata": None})
        gen = LabelGenerator(rm)  # type: ignore[arg-type]
        gen.add_item(393)
        assert gen.records[0]["received_date"] == ""


class TestLookupLists:
    """The add-resource page loads existing compounds and storage places into dropdowns."""

    def test_compounds_list_is_trimmed_and_sorted(self, client, monkeypatch):
        fake_rm = SimpleNamespace(get_compounds=lambda: [
            {"id": 72, "name": "acetone", "cas_number": "67-64-1", "molecular_formula": "C3H6O", "smiles": "CC(C)=O",
             "is_flammable": 1},
            {"id": 111, "name": "Chlorobenzene", "cas_number": "108-90-7", "molecular_formula": None},
            {"id": 196, "name": None, "cas_number": None, "molecular_formula": None},
        ])
        monkeypatch.setattr(interface, "rm", lambda: fake_rm)
        resp = client.get("/compounds_list")
        assert resp.status_code == 200
        assert resp.get_json() == [
            {"id": 196, "name": "", "cas": "", "formula": "", "hazards": [], "peroxide_class": None},
            {"id": 72, "name": "acetone", "cas": "67-64-1", "formula": "C3H6O",
             "hazards": ["Flammable"], "peroxide_class": None},
            {"id": 111, "name": "Chlorobenzene", "cas": "108-90-7", "formula": "",
             "hazards": [], "peroxide_class": None},
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

    @pytest.mark.parametrize("path", ["/compounds_list", "/storage_tree", "/bottle_form"])
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
    """A PubChem GHS Classification record, shaped like the real ones. Each source is a list of
    pictogram codes, or a dict {source, pictograms, reports, not_hazardous_percent}."""
    info, references = [], []
    for ref, src in enumerate(sources, start=1):
        if isinstance(src, list):
            src = {"pictograms": src}
        references.append({"ReferenceNumber": ref, "SourceName": src.get("source", f"Source {ref}")})
        if "not_hazardous_percent" in src:
            info.append({"ReferenceNumber": ref, "Name": "Note", "Value": {"StringWithMarkup": [{"String":
                f"This chemical does not meet GHS hazard criteria for {src['not_hazardous_percent']}% (x of y) of all reports."}]}})
        if src.get("pictograms"):
            info.append({"ReferenceNumber": ref, "Name": "Pictogram(s)", "Value": {"StringWithMarkup": [
                {"String": "", "Markup": [{"URL": f"https://pubchem.ncbi.nlm.nih.gov/images/ghs/{c}.svg", "Type": "Icon"}
                                          for c in src["pictograms"]]}]}})
        if "reports" in src:
            info.append({"ReferenceNumber": ref, "Name": "ECHA C&L Notifications Summary", "Value": {"StringWithMarkup": [
                {"String": f"Aggregated GHS information provided per {src['reports']} reports by companies from 9 notifications."}]}})
    section = {"TOCHeading": "GHS Classification", "Information": info}
    return {"Record": {"Reference": references, "Section": [{"TOCHeading": "Safety and Hazards", "Section": [
        {"TOCHeading": "Hazards Identification", "Section": [section]}]}]}}


OFFICIAL = "Regulation (EC) No 1272/2008 of the European Parliament and of the Council"
ECHA = "European Chemicals Agency (ECHA)"


THF_PROPERTIES = {"PropertyTable": {"Properties": [{
    "CID": 8028, "Title": "Tetrahydrofuran", "IUPACName": "oxolane", "MolecularFormula": "C4H8O",
    "MolecularWeight": "72.11", "SMILES": "C1CCOC1", "InChI": "InChI=1S/C4H8O/c1-2-4-5-3-1/h1-4H2",
    "InChIKey": "WYURNTSHIVDZCO-UHFFFAOYSA-N"}]}}
THF_SYNONYMS = {"InformationList": {"Information": [
    {"CID": 8028, "Synonym": ["tetrahydrofuran", "THF", "109-99-9", "oxolane", "1-23-4567"]}]}}


class TestPubChem:
    """eln_common.pubchem with PubChem's answers faked (shapes copied from real ones)."""

    def test_without_eu_or_echa_data_other_sources_are_combined(self, monkeypatch):
        fake = FakePubChem({"/pug_view/data/compound/8028/": ghs_answer(["GHS02", "GHS07"], ["GHS08"])})
        monkeypatch.setattr(pubchem, "requests", fake)
        assert pubchem.ghs_pictograms(8028) == ["GHS02", "GHS07", "GHS08"]
        assert fake.calls[0][1]["params"] == {"heading": "GHS Classification"}

    def test_official_eu_classification_wins(self, monkeypatch):
        # hydrogen peroxide: Japan's NITE lists concentrated grades with more pictograms
        monkeypatch.setattr(pubchem, "requests", FakePubChem({"/pug_view/": ghs_answer(
            {"source": OFFICIAL, "pictograms": ["GHS03", "GHS05", "GHS07"]},
            {"source": ECHA, "pictograms": ["GHS03", "GHS05", "GHS07"], "reports": 1964, "not_hazardous_percent": 0.1},
            {"source": "NITE-CMC", "pictograms": ["GHS03", "GHS05", "GHS06", "GHS07", "GHS08", "GHS09"]})}))
        assert pubchem.ghs_pictograms(784) == ["GHS03", "GHS05", "GHS07"]

    def test_echa_main_summary_saying_not_hazardous_means_none(self, monkeypatch):
        # water: 99.5% of 1876 reports say not hazardous; a 39-report group (another substance) says GHS07
        monkeypatch.setattr(pubchem, "requests", FakePubChem({"/pug_view/": ghs_answer(
            {"source": ECHA, "reports": 1876, "not_hazardous_percent": 99.5},
            {"source": ECHA, "pictograms": ["GHS07"], "reports": 39})}))
        assert pubchem.ghs_pictograms(962) == []

    def test_echa_main_summary_is_used_without_eu_classification(self, monkeypatch):
        monkeypatch.setattr(pubchem, "requests", FakePubChem({"/pug_view/": ghs_answer(
            {"source": ECHA, "pictograms": ["GHS02", "GHS07"], "reports": 500, "not_hazardous_percent": 2},
            {"source": ECHA, "pictograms": ["GHS06"], "reports": 3},
            {"source": "NITE-CMC", "pictograms": ["GHS09"]})}))
        assert pubchem.ghs_pictograms(1) == ["GHS02", "GHS07"]

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


STORAGE = [
    {"id": 4, "name": "Room 3057", "parent_id": None, "full_path": "Room 3057"},
    {"id": 5, "name": "Front hood", "parent_id": 4, "full_path": "Room 3057 > Front hood"},
    {"id": 6, "name": "Flammable cabinet", "parent_id": 5, "full_path": "Room 3057 > Front hood > Flammable cabinet"},
    {"id": 7, "name": "Corrosive cabinet", "parent_id": 5, "full_path": "Room 3057 > Front hood > Corrosive cabinet"},
    {"id": 16, "name": "Room 3053", "parent_id": None, "full_path": "Room 3053"},
    {"id": 21, "name": "Shelf 1", "parent_id": 16, "full_path": "Room 3053 > Shelf 1"},
]


class FakeStorageRM:
    """Stand-in for the storage calls of Resource_Manager."""

    def __init__(self, units=STORAGE, create_returns=30):
        self.units = units
        self.create_returns = create_returns
        self.created = []

    def get_storage_units(self):
        return self.units

    def create_storage_unit(self, name, parent_id):
        self.created.append((name, parent_id))
        return self.create_returns


class TestStoragePlaces:
    """eLabFTW accepts any name, so near-duplicates are caught before creating."""

    def test_new_name_is_created_with_its_full_path(self):
        rm = FakeStorageRM()
        place = storage_places.create_place_safely(rm, "  Shelf   2 ", 16)
        assert rm.created == [("Shelf 2", 16)]
        assert place == {"id": 30, "name": "Shelf 2", "parent_id": 16, "full_path": "Room 3053 > Shelf 2"}

    @pytest.mark.parametrize("name", ["Flammable cabinet", "flammable CABINET", " Flammable  cabinet "])
    def test_same_name_in_same_parent_is_refused_even_if_confirmed(self, name):
        rm = FakeStorageRM()
        with pytest.raises(storage_places.PlaceClash) as e:
            storage_places.create_place_safely(rm, name, 5, confirm_similar=True)
        assert e.value.exact and e.value.existing["id"] == 6
        assert rm.created == []

    def test_similar_name_needs_confirmation(self):
        rm = FakeStorageRM()
        with pytest.raises(storage_places.PlaceClash) as e:
            storage_places.create_place_safely(rm, "Flamable cabinet", 5)
        assert not e.value.exact and e.value.existing["id"] == 6
        assert rm.created == []
        storage_places.create_place_safely(rm, "Flamable cabinet", 5, confirm_similar=True)
        assert rm.created == [("Flamable cabinet", 5)]

    def test_same_name_in_another_parent_is_fine(self):
        rm = FakeStorageRM()
        storage_places.create_place_safely(rm, "Flammable cabinet", 16)
        assert rm.created == [("Flammable cabinet", 16)]

    @pytest.mark.parametrize("name", ["Corrosive shelf", "Shelf 2", "Base cabinet"])
    def test_different_names_are_not_similar(self, name):
        assert storage_places.find_clash(name, 16, STORAGE + [
            {"id": 22, "name": "Acid cabinet", "parent_id": 16}]) is None

    def test_unknown_parent(self):
        with pytest.raises(storage_places.UnknownParent):
            storage_places.create_place_safely(FakeStorageRM(), "Shelf 2", 999)

    @pytest.mark.parametrize("name", ["", "   ", "x" * 256])
    def test_bad_names(self, name):
        with pytest.raises(ValueError):
            storage_places.create_place_safely(FakeStorageRM(), name, 16)


class TestStorageRoutes:
    def test_create_returns_201(self, client, monkeypatch):
        monkeypatch.setattr(interface, "rm", lambda: FakeStorageRM())
        resp = client.post("/storage_units", json={"name": "Shelf 2", "parent_id": 16})
        assert resp.status_code == 201 and resp.get_json()["full_path"] == "Room 3053 > Shelf 2"

    def test_exact_clash_is_409_with_existing(self, client, monkeypatch):
        monkeypatch.setattr(interface, "rm", lambda: FakeStorageRM())
        resp = client.post("/storage_units", json={"name": "flammable cabinet", "parent_id": 5, "confirm": True})
        assert resp.status_code == 409
        assert resp.get_json()["exact"] is True and resp.get_json()["existing"]["id"] == 6

    def test_similar_is_409_then_confirm_creates(self, client, monkeypatch):
        rm = FakeStorageRM()
        monkeypatch.setattr(interface, "rm", lambda: rm)
        resp = client.post("/storage_units", json={"name": "Flamable cabinet", "parent_id": 5})
        assert resp.status_code == 409 and resp.get_json()["exact"] is False
        resp = client.post("/storage_units", json={"name": "Flamable cabinet", "parent_id": 5, "confirm": True})
        assert resp.status_code == 201

    def test_unknown_parent_is_404(self, client, monkeypatch):
        monkeypatch.setattr(interface, "rm", lambda: FakeStorageRM())
        assert client.post("/storage_units", json={"name": "Shelf 2", "parent_id": 999}).status_code == 404

    @pytest.mark.parametrize("body", [{}, {"name": "Shelf 2"}, {"name": "Shelf 2", "parent_id": "16"},
                                      {"name": "Shelf 2", "parent_id": True}, {"parent_id": 16},
                                      {"name": " ", "parent_id": 16}])
    def test_bad_input_is_400(self, client, monkeypatch, body):
        monkeypatch.setattr(interface, "rm", lambda: FakeStorageRM())
        assert client.post("/storage_units", json=body).status_code == 400

    def test_needs_an_api_key(self, client):
        assert client.post("/storage_units", json={"name": "Shelf 2", "parent_id": 16}).status_code == 401


def _field(position, type_="text", **extra):
    return {"type": type_, "value": "", "position": position, **extra}


CHEMICAL_TEMPLATE = {"id": 2, "title": "Chemical Compound", "metadata": json.dumps({
    "elabftw": {"display_main_text": True},
    "extra_fields": {
        "CAS": _field(1), "Location": _field(2, "select", options=["Front hood"]),
        "Quantity": _field(3, "number"), "Received": _field(4, "date"), "Room": _field(5, "select"),
        "State": _field(6, "select", options=["Solid", "Liquid", "Gas"]), "Purity": _field(7, "number", unit="%"),
        "Lot number": _field(8), "Full name": _field(9), "SMILES": _field(10), "Manufacturer": _field(11, "select"),
        "Molecular Weight": _field(12, "number"), "Hazards Link": _field(13), "Pubchem Link": _field(14),
    }})}
POLYMER_TEMPLATE = {"id": 3, "title": "Polymer", "metadata": json.dumps({"extra_fields": {
    "Mw": _field(1, "number"), "Full name": _field(2), "SMILES": _field(3), "Location": _field(4),
    "Quantity": _field(5, "number"), "Room": _field(6)}})}


class FakeBottleRM:
    """Stand-in for the calls create_bottles makes; records them in order. Bottles get
    ids 640, 641...; fail_create_at=n makes the n-th create fail."""

    def __init__(self, fail=(), existing=(), fail_create_at=None):
        self.calls = []
        self.fail_create_at = fail_create_at
        self.next_id = 640
        self.fail = set(fail)
        self.existing = list(existing)  # current bottles, as the search returns them
        self.searches = []

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            raise RuntimeError(f"{name} refused")

    def get_items_type(self, id):
        templates = {2: CHEMICAL_TEMPLATE, 3: POLYMER_TEMPLATE}
        if id not in templates:
            raise RuntimeError("404")
        return templates[id]

    def get_compounds(self):
        return [THF_COMPOUND, {"id": 72, "name": "Acetone", "cas_number": "67-64-1", "is_flammable": 1}]

    def get_storage_units(self):
        return STORAGE

    def create_item_from_template(self, template):
        self._record("create", template)
        if self.next_id - 639 == self.fail_create_at:
            raise RuntimeError("eLabFTW is down")
        self.next_id += 1
        return self.next_id - 1

    def change_item(self, id, body):
        self._record("change", id, body)

    def link_compound(self, item_id, compound_id):
        self._record("link", item_id, compound_id)

    def add_to_storage(self, item_id, storage_id, amount, unit):
        self._record("storage", item_id, storage_id, amount, unit)

    def upload_file(self, id, path):
        self._record("upload", id, path)

    def add_tag(self, item_id, tag):
        self._record("tag", item_id, tag)

    def search_items_by_field(self, field, value):
        self.searches.append((field, value))
        return [b for b in self.existing
                if value.lower() in json.loads(b["metadata"])["extra_fields"].get(field, {}).get("value", "").lower()]

    def get_item(self, id):
        return next(b for b in self.existing if b["id"] == id)


def existing_bottle(id, title, links=(), **values):
    """A current bottle as eLabFTW's search returns it (get_item also gives its compound links)."""
    fields = {name.replace("_", " "): {"value": v} for name, v in values.items()}
    return {"id": id, "title": title, "metadata": json.dumps({"extra_fields": fields}),
            "compounds_links": [{"id": c} for c in links]}


THF_COMPOUND = {"id": 77, "name": "Tetrahydrofuran", "smiles": "C1CCOC1", "cas_number": "109-99-9",
                "inchi_key": "WYURNTSHIVDZCO-UHFFFAOYSA-N", "is_flammable": 1, "is_hazardous2health": 1,
                "is_serious_health_hazard": 1, "is_toxic": 0}
THF_TAGS = ["Flammable", "Health hazard", "Serious health hazard", "Peroxide former: B"]
THF_BOTTLE = {"category": 2, "title": " Tetrahydrofuran ", "compounds": [77],
              "storage": {"place_id": 6, "amount": 500, "unit": "mL"},
              "fields": {"Manufacturer": "Sigma-Aldrich", "Lot number": "SHBM1234", "Purity": 99.9,
                         "State": "Liquid"}}


@pytest.fixture
def fake_image(monkeypatch):
    monkeypatch.setattr(add_bottle, "generate_image", lambda smiles: f"/tmp/{smiles}.png")


class TestAddBottle:
    def test_creates_links_places_and_draws_in_order(self, fake_image):
        rm = FakeBottleRM()
        assert add_bottle.create_bottles(rm, THF_BOTTLE) == {
            "bottles": [{"id": 640, "tags": THF_TAGS, "problems": []}], "problems": []}
        assert [c[0] for c in rm.calls] == ["create", "change", "link"] + ["tag"] * 4 + ["storage", "upload"]
        assert rm.calls[0] == ("create", 2)
        assert rm.calls[2] == ("link", 640, 77)
        assert [c[2] for c in rm.calls if c[0] == "tag"] == THF_TAGS
        assert rm.calls[-2] == ("storage", 640, 6, 500, "mL")
        assert rm.calls[-1] == ("upload", 640, "/tmp/C1CCOC1.png")

    def test_bottle_keeps_only_its_own_fields(self, fake_image):
        rm = FakeBottleRM()
        add_bottle.create_bottles(rm, THF_BOTTLE)
        body = rm.calls[1][2]
        assert body["title"] == "Tetrahydrofuran"
        metadata = json.loads(body["metadata"])
        assert sorted(metadata["extra_fields"]) == ["CAS", "Lot number", "Manufacturer", "Purity", "Received", "State"]
        assert metadata["extra_fields"]["Purity"] == {**_field(7, "number", unit="%"), "value": "99.9"}
        assert metadata["extra_fields"]["CAS"]["value"] == ""
        assert metadata["elabftw"] == {"display_main_text": True}

    def test_polymer_without_compounds_keeps_its_chemistry_fields(self, fake_image):
        rm = FakeBottleRM()
        add_bottle.create_bottles(rm, {"category": 3, "title": "P3HT", "fields": {"Mw": 50000, "SMILES": "*c1ccsc1*"},
                                      "storage": {"place_id": 21, "amount": 2, "unit": "g"}})
        metadata = json.loads(rm.calls[1][2]["metadata"])
        assert sorted(metadata["extra_fields"]) == ["Full name", "Mw", "SMILES"]
        assert [c[0] for c in rm.calls] == ["create", "change", "storage"]  # no link, tags or image

    def test_micro_sign_becomes_greek_mu(self, fake_image):
        rm = FakeBottleRM()
        add_bottle.create_bottles(rm, {**THF_BOTTLE, "storage": {"place_id": 6, "amount": 250, "unit": "\u00b5L"}})
        assert [c for c in rm.calls if c[0] == "storage"][0][-1] == "\u03bcL"

    @pytest.mark.parametrize("change, message", [
        ({"category": None}, "Choose a category"),
        ({"category": 99}, "no category #99"),
        ({"title": "  "}, "needs a name"),
        ({"compounds": [999]}, "no compound #999"),
        ({"compounds": "77"}, "list of compound ids"),
        ({"storage": None}, "where the bottle is kept"),
        ({"storage": {"place_id": 999, "amount": 1, "unit": "g"}}, "no storage place #999"),
        ({"storage": {"place_id": 6, "amount": -1, "unit": "g"}}, "0 or more"),
        ({"storage": {"place_id": 6, "amount": "500", "unit": "mL"}}, "must be a number"),
        ({"storage": {"place_id": 6, "amount": 5, "unit": "gallons"}}, "Unknown unit"),
        ({"fields": {"Room": "3057"}}, "not a field"),
        ({"fields": {"SMILES": "CCO"}}, "not a field"),  # lives in the compound now
        ({"fields": {"Purity": [99]}}, "text or a number"),
        ({"count": 0}, "between 1 and 20"),
        ({"count": 21}, "between 1 and 20"),
        ({"count": "4"}, "between 1 and 20"),
    ])
    def test_bad_request_creates_nothing(self, fake_image, change, message):
        rm = FakeBottleRM()
        with pytest.raises(add_bottle.InvalidBottle, match=message):
            add_bottle.create_bottles(rm, {**THF_BOTTLE, **change})
        assert rm.calls == []

    def test_later_failures_are_reported_and_the_rest_still_runs(self, fake_image):
        rm = FakeBottleRM(fail={"link", "tag", "storage"})
        result = add_bottle.create_bottles(rm, THF_BOTTLE)["bottles"][0]
        assert result["id"] == 640 and result["tags"] == []
        assert [p.split(" failed")[0] for p in result["problems"]] == [
            "Linking compound #77"] + [f"Adding the tag '{t}'" for t in THF_TAGS] + [
            "Putting it in its storage place"]
        assert [c[0] for c in rm.calls][-2:] == ["storage", "upload"]

    def test_solution_gets_tags_of_both_compounds_once(self, fake_image):
        rm = FakeBottleRM()
        result = add_bottle.create_bottles(rm, {**THF_BOTTLE, "compounds": [72, 77]})["bottles"][0]
        assert result["tags"] == THF_TAGS  # Flammable from both, listed once
        assert [c for c in rm.calls if c[0] == "link"] == [("link", 640, 72), ("link", 640, 77)]

    def test_units_offered_per_state_are_elabftw_units(self):
        for units in add_bottle.UNITS_BY_STATE.values():
            assert set(units) <= set(add_bottle.UNITS)


class TestSeveralBottles:
    def test_count_creates_that_many_bottles_with_their_own_ids(self, fake_image):
        old = existing_bottle(522, "THF (old)", Lot_number="OTHER", CAS="109-99-9")
        rm = FakeBottleRM(existing=[old])
        result = add_bottle.create_bottles(rm, {**THF_BOTTLE, "count": 3})
        assert [b["id"] for b in result["bottles"]] == [640, 641, 642]
        assert [c[1] for c in rm.calls if c[0] == "storage"] == [640, 641, 642]
        assert len(rm.searches) == 1  # the same-lot question is asked once per request

    def test_stops_and_reports_when_a_later_bottle_fails(self, fake_image):
        rm = FakeBottleRM(fail_create_at=3)
        result = add_bottle.create_bottles(rm, {**THF_BOTTLE, "count": 4})
        assert [b["id"] for b in result["bottles"]] == [640, 641]
        assert result["problems"] == ["Only 2 of 4 bottles were created: eLabFTW is down"]

    def test_first_bottle_failing_creates_nothing(self, fake_image):
        with pytest.raises(RuntimeError):
            add_bottle.create_bottles(FakeBottleRM(fail_create_at=1), {**THF_BOTTLE, "count": 2})


class TestSameLot:
    """Same lot + manufacturer + chemical as a current bottle: ask before creating, since
    it may be another bottle of the order or this bottle entered again."""

    def test_same_lot_supplier_and_cas_is_refused(self, fake_image):
        old = existing_bottle(522, "THF (old)", Lot_number="shbm1234", Manufacturer="sigma-aldrich", CAS="109-99-9")
        rm = FakeBottleRM(existing=[old])
        with pytest.raises(add_bottle.SameLotBottles) as e:
            add_bottle.create_bottles(rm, THF_BOTTLE)
        assert e.value.bottles == [{"id": 522, "title": "THF (old)"}]
        assert rm.calls == [] and rm.searches == [("Lot number", "SHBM1234")]

    def test_linked_compound_counts_as_same_chemical(self, fake_image):
        old = existing_bottle(600, "Tetrahydrofuran", links=[77], Lot_number="SHBM1234")
        with pytest.raises(add_bottle.SameLotBottles):
            add_bottle.create_bottles(FakeBottleRM(existing=[old]), THF_BOTTLE)

    def test_confirmed_duplicate_is_created(self, fake_image):
        old = existing_bottle(522, "THF (old)", Lot_number="SHBM1234", CAS="109-99-9")
        rm = FakeBottleRM(existing=[old])
        assert add_bottle.create_bottles(rm, {**THF_BOTTLE, "confirm_same_lot": True})["bottles"][0]["id"] == 640

    @pytest.mark.parametrize("old", [
        existing_bottle(1, "THF other supplier", Lot_number="SHBM1234", Manufacturer="Fisher", CAS="109-99-9"),
        existing_bottle(2, "Other chemical", Lot_number="SHBM1234", CAS="67-64-1"),
        existing_bottle(3, "Longer lot", Lot_number="SHBM12345", CAS="109-99-9"),
    ])
    def test_not_the_same_bottle(self, fake_image, old):
        assert add_bottle.create_bottles(FakeBottleRM(existing=[old]), THF_BOTTLE)["bottles"][0]["id"] == 640

    def test_no_lot_number_no_check(self, fake_image):
        rm = FakeBottleRM()
        fields = {k: v for k, v in THF_BOTTLE["fields"].items() if k != "Lot number"}
        add_bottle.create_bottles(rm, {**THF_BOTTLE, "fields": fields})
        assert rm.searches == []

    def test_route_answers_409_with_links(self, client, monkeypatch, fake_image):
        old = existing_bottle(522, "THF (old)", Lot_number="SHBM1234", CAS="109-99-9")
        monkeypatch.setattr(interface, "rm", lambda: FakeBottleRM(existing=[old]))
        resp = client.post("/resources", json=THF_BOTTLE)
        assert resp.status_code == 409
        [dup] = resp.get_json()["same_lot"]
        assert dup["id"] == 522 and dup["url"].endswith("522")
        assert "already have an ELN label" in resp.get_json()["question"]


class TestBottleTags:
    """Hazard tags from the compound's flags; peroxide class from the real EPA lists."""

    def test_all_four_lists_are_read(self):
        assert set(bottle_tags.peroxide_classes().values()) == {"A", "B", "C", "D"}

    @pytest.mark.parametrize("compound, expected", [
        ({"cas_number": "109-99-9"}, "B"),                                   # THF
        ({"cas_number": "60-29-7"}, "B"),                                    # diethyl ether
        ({"cas_number": "80-62-6"}, "C"),                                    # methyl methacrylate
        ({"cas_number": "0-00-0", "inchi_key": "WYURNTSHIVDZCO-UHFFFAOYSA-N"}, "B"),  # THF by structure
        ({"cas_number": "67-64-1"}, None),                                   # acetone
        ({}, None),
    ])
    def test_peroxide_class(self, compound, expected):
        assert bottle_tags.peroxide_class(compound) == expected

    def test_tags_for_thf(self):
        assert bottle_tags.tags_for([THF_COMPOUND]) == THF_TAGS

    def test_no_compounds_no_tags(self):
        assert bottle_tags.tags_for([]) == []


class TestBottleForm:
    @pytest.mark.parametrize("names, slots", [
        ({"State", "CAS"}, ["Chemical"]),
        ({"State", "Solvent", "Solvent CAS"}, ["Dissolved chemical", "Solvent"]),
        ({"State", "Mw", "Mn"}, []),
        ({"Room"}, None),  # Instrument: not a bottle
    ])
    def test_compound_slots(self, names, slots):
        assert add_bottle.compound_slots({n: {} for n in names}) == slots

    def test_route_lists_categories_with_their_kind_and_own_fields(self, client, monkeypatch):
        instrument = {"id": 1, "title": "Instrument", "metadata": json.dumps({"extra_fields": {
            "Maintenance interval": _field(2), "Room": _field(1)}})}
        templates = {1: instrument, 2: CHEMICAL_TEMPLATE}
        fake_rm = SimpleNamespace(get_items_types=lambda: [{"id": i, "title": t["title"]} for i, t in templates.items()],
                                  get_items_type=lambda id: templates[id])
        monkeypatch.setattr(interface, "rm", lambda: fake_rm)
        resp = client.get("/bottle_form")
        assert resp.status_code == 200
        categories = resp.get_json()["categories"]
        assert [(c["id"], c["kind"], c["compound_slots"]) for c in categories] == [
            (1, "instrument", []), (2, "bottle", ["Chemical"])]
        # an instrument category keeps all its fields (Room too), in template order
        assert [f["name"] for f in categories[0]["fields"]] == ["Room", "Maintenance interval"]
        names = [f["name"] for f in categories[1]["fields"]]
        assert names == ["CAS", "Received", "State", "Purity", "Lot number", "Manufacturer"]  # template order
        assert resp.get_json()["units_by_state"]["Liquid"] == ["\u03bcL", "mL", "L"]

    def test_page_is_served(self, client):
        resp = client.get("/add_bottle_interface")
        assert resp.status_code == 200 and b"add_bottle.js" in resp.data


class TestCreateResourceRoute:
    def test_returns_201_with_id_url_and_problems(self, client, monkeypatch, fake_image):
        monkeypatch.setattr(interface, "rm", lambda: FakeBottleRM())
        resp = client.post("/resources", json=THF_BOTTLE)
        assert resp.status_code == 201
        [bottle] = resp.get_json()["bottles"]
        assert bottle["id"] == 640 and bottle["problems"] == [] and bottle["tags"] == THF_TAGS
        assert bottle["url"].endswith("640") and resp.get_json()["problems"] == []

    def test_bad_request_is_400(self, client, monkeypatch):
        monkeypatch.setattr(interface, "rm", lambda: FakeBottleRM())
        resp = client.post("/resources", json={**THF_BOTTLE, "title": ""})
        assert resp.status_code == 400 and "needs a name" in resp.get_json()["error"]

    def test_failed_create_is_500(self, client, monkeypatch):
        monkeypatch.setattr(interface, "rm", lambda: FakeBottleRM(fail={"create"}))
        resp = client.post("/resources", json=THF_BOTTLE)
        assert resp.status_code == 500 and "not created" in resp.get_json()["error"]

    def test_needs_an_api_key(self, client):
        assert client.post("/resources", json=THF_BOTTLE).status_code == 401


class FakeScannerRM:
    """Stand-in for the calls the scanner actions make; bottles map id -> containers."""

    def __init__(self, bottles, fail_move=()):
        self.bottles = bottles
        self.fail_move = set(fail_move)
        self.moves, self.changes, self.amounts = [], [], []
        self.steps = {}

    def get_storage_units(self):
        return STORAGE

    def get_item(self, id):
        if id not in self.bottles:
            raise RuntimeError("404 Not Found")
        return {"id": id, "containers": self.bottles[id]}

    def move_container(self, item_id, container_id, storage_id):
        if item_id in self.fail_move:
            raise RuntimeError("403 Forbidden")
        self.moves.append((item_id, container_id, storage_id))

    def change_item(self, id, body):
        if id not in self.bottles:
            raise RuntimeError("404 Not Found")
        self.changes.append((id, body))

    def set_container_amount(self, item_id, container_id, amount):
        self.amounts.append((item_id, container_id, amount))

    def get_steps(self, item_id):
        return self.steps.get(item_id, [])

    def add_step(self, item_id, body):
        step = {"id": 100 + sum(len(v) for v in self.steps.values()), "body": body, "finished": 0, "deadline": None}
        self.steps.setdefault(item_id, []).append(step)
        return step["id"]

    def set_step(self, item_id, step_id, fields):
        next(s for s in self.steps[item_id] if s["id"] == step_id).update(fields)

    def finish_step(self, item_id, step_id):
        step = next(s for s in self.steps[item_id] if s["id"] == step_id)
        step.update(finished=1, deadline=None)


class FakeBottleItemsRM(FakeScannerRM):
    """FakeScannerRM whose bottles also have tags and an Opened field, as get_item returns them."""

    def __init__(self, items):
        super().__init__({i: [{"id": 234}] for i in items})
        self.items = items
        self.steps = {}

    def get_item(self, id):
        if id not in self.items:
            raise RuntimeError("404 Not Found")
        tags, opened = self.items[id]
        return {"id": id, "tags": tags, "containers": self.bottles[id],
                "metadata": json.dumps({"extra_fields": {"Opened": {"value": opened}}})}

    def change_item(self, id, body):
        super().change_item(id, body)
        if "metadata" in body:  # remember the Opened date the action wrote
            self.items[id] = (self.items[id][0], json.loads(body["metadata"])["extra_fields"]["Opened"]["value"])


class TestMoveBottles:
    def test_moves_each_bottles_storage_entry(self):
        rm = FakeScannerRM({624: [{"id": 234, "storage_id": 7}], 625: [{"id": 235, "storage_id": 7}]})
        result = bottle_actions.move_bottles(rm, [624, 625], 6)
        assert rm.moves == [(624, 234, 6), (625, 235, 6)]  # the entry's own id, then the place's
        assert result == {"moved": [624, 625], "place": "Room 3057 > Front hood > Flammable cabinet",
                          "problems": []}

    def test_bottles_without_one_place_are_reported_not_guessed(self):
        rm = FakeScannerRM({1: [], 2: [{"id": 8}, {"id": 9}], 3: [{"id": 10}]}, fail_move={3})
        result = bottle_actions.move_bottles(rm, [1, 2, 3, 4], 6)
        assert result["moved"] == [] and rm.moves == []
        assert [p.split(" ")[0] for p in result["problems"]] == ["#1", "#2", "#3:", "#4:"]
        assert "no place yet" in result["problems"][0] and "in 2 places" in result["problems"][1]

    def test_unknown_place_moves_nothing(self):
        rm = FakeScannerRM({624: [{"id": 234}]})
        with pytest.raises(bottle_actions.UnknownPlace):
            bottle_actions.move_bottles(rm, [624], 999)
        assert rm.moves == []

    def test_route(self, client, monkeypatch):
        monkeypatch.setattr(interface, "rm", lambda: FakeScannerRM({624: [{"id": 234}]}))
        resp = client.post("/move_to_storage", json={"id": ["624"], "storage_id": 6})
        assert resp.status_code == 200 and resp.get_json()["moved"] == [624]
        assert client.post("/move_to_storage", json={"id": [624], "storage_id": 999}).status_code == 404

    @pytest.mark.parametrize("body", [{"id": [624]}, {"id": [624], "storage_id": "6"},
                                      {"id": ["x"], "storage_id": 6}, {"id": 624, "storage_id": 6}])
    def test_route_bad_input_is_400(self, client, body):
        assert client.post("/move_to_storage", json=body).status_code == 400

    def test_old_location_routes_are_gone(self, client):
        assert client.post("/change_location", json={"id": [1], "location": "x"}).status_code == 404
        assert client.get("/get_locations").status_code == 404


class TestMarkEmpty:
    def test_status_empty_and_every_storage_entry_to_zero(self):
        rm = FakeScannerRM({624: [{"id": 234}], 700: [{"id": 8}, {"id": 9}], 393: []})
        result = bottle_actions.mark_empty(rm, [624, 700, 393], empty_status=5)
        assert result == {"emptied": [624, 700, 393], "problems": []}
        assert rm.changes == [(624, {"status": 5}), (700, {"status": 5}), (393, {"status": 5})]
        assert rm.amounts == [(624, 234, 0), (700, 8, 0), (700, 9, 0)]

    def test_unknown_bottle_is_reported(self):
        result = bottle_actions.mark_empty(FakeScannerRM({}), [999], empty_status=5)
        assert result["emptied"] == [] and result["problems"][0].startswith("#999")

    def test_route(self, client, monkeypatch):
        rm = FakeScannerRM({624: [{"id": 234}]})
        monkeypatch.setattr(interface, "rm", lambda: rm)
        resp = client.post("/mark_empty", json={"id": [624]})
        assert resp.status_code == 200 and resp.get_json()["emptied"] == [624]
        assert rm.amounts == [(624, 234, 0)]


class TestRoutineChecks:
    def test_rules_file_covers_the_peroxide_tags(self):
        assert {r["tag"]: r["every_months"] for r in routine_checks.rules()} == {
            "Peroxide former: A": 3, "Peroxide former: B": 6, "Peroxide former: C": 6, "Peroxide former: D": 12}
        # the tags match the ones bottle_tags gives new bottles
        assert {f"Peroxide former: {c}" for c in "ABCD"} == {r["tag"] for r in routine_checks.rules()}

    def test_rule_for_reads_elabftw_tags(self):
        assert routine_checks.rule_for("Flammable|Peroxide former: B")["every_months"] == 6
        assert routine_checks.rule_for("Flammable") is None and routine_checks.rule_for(None) is None

    @pytest.mark.parametrize("start, months, due", [
        (date(2026, 10, 6), 6, date(2027, 4, 6)),
        (date(2026, 8, 31), 6, date(2027, 2, 28)),   # no 31 February
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2027, 12, 15), 12, date(2028, 12, 15)),
    ])
    def test_add_months(self, start, months, due):
        assert routine_checks.add_months(start, months) == due


TODAY = date(2026, 10, 6)


class TestBottleLifecycle:
    """Mark Open adds the check step, Tested ticks it and adds the next, Mark Empty closes it."""

    def test_open_tested_empty(self):
        rm = FakeBottleItemsRM({522: ("Flammable|Peroxide former: B", "")})
        opened = bottle_actions.mark_open(rm, [522], open_status=4, today=TODAY)
        assert opened == {"opened": [522], "checks": [
            {"id": 522, "step": "Test for peroxides (class B)", "due": "2027-04-06"}], "problems": []}
        [step] = rm.steps[522]
        assert step["body"] == "Test for peroxides (class B), due 2027-04-06"
        assert step["deadline"] == "2027-04-06 09:00:00"

        tested = bottle_actions.mark_tested(rm, [522], today=date(2027, 4, 2))
        assert tested == {"tested": [{"id": 522, "step": "Test for peroxides (class B)",
                                      "next_due": "2027-10-02"}], "problems": []}
        assert [(s["finished"], s["body"]) for s in rm.steps[522]] == [
            (1, "Test for peroxides (class B), due 2027-04-06"),
            (0, "Test for peroxides (class B), due 2027-10-02")]

        bottle_actions.mark_empty(rm, [522], empty_status=5, today=date(2027, 7, 15))
        assert [(s["finished"], s["body"]) for s in rm.steps[522]][-1] == (
            1, "Test for peroxides (class B), due 2027-10-02: closed, bottle marked empty on 2027-07-15 (no test needed)")
        assert routine_checks.open_check_steps(rm.steps[522]) == []

    def test_open_without_routine_check_adds_no_step(self):
        rm = FakeBottleItemsRM({72: ("Flammable", "")})
        result = bottle_actions.mark_open(rm, [72], open_status=4, today=TODAY)
        assert result["opened"] == [72] and result["checks"] == [] and rm.steps == {}

    def test_already_open_is_reported_and_not_changed(self):
        rm = FakeBottleItemsRM({522: ("Peroxide former: B", "2026-09-01")})
        result = bottle_actions.mark_open(rm, [522], open_status=4, today=TODAY)
        assert result["opened"] == [] and "already marked open on 2026-09-01" in result["problems"][0]
        assert rm.changes == [] and rm.steps == {}

    def test_tested_needs_a_check_and_an_open_bottle(self):
        rm = FakeBottleItemsRM({72: ("Flammable", "2026-09-01"), 522: ("Peroxide former: B", "")})
        result = bottle_actions.mark_tested(rm, [72, 522, 999], today=TODAY)
        assert result["tested"] == [] and rm.steps == {}
        assert "no routine check" in result["problems"][0]
        assert "not marked open yet" in result["problems"][1]
        assert result["problems"][2].startswith("#999")

    def test_empty_bottle_without_steps_is_fine(self):
        rm = FakeBottleItemsRM({72: ("Flammable", "2026-09-01")})
        assert bottle_actions.mark_empty(rm, [72], empty_status=5, today=TODAY) == {"emptied": [72], "problems": []}

    def test_routes(self, client, monkeypatch):
        rm = FakeBottleItemsRM({522: ("Peroxide former: B", "")})
        monkeypatch.setattr(interface, "rm", lambda: rm)
        resp = client.post("/mark_open", json={"id": [522]})
        assert resp.status_code == 200 and resp.get_json()["checks"][0]["id"] == 522
        resp = client.post("/mark_tested", json={"id": [522]})
        assert resp.status_code == 200 and resp.get_json()["tested"][0]["id"] == 522
        assert client.post("/mark_tested", json={"id": []}).status_code == 400


class TestCreateItemFromTemplate:
    """New resources start from their template, so they get its category and
    default status (items created from a bare category had no status)."""

    def test_posts_only_the_template(self):
        posted = []
        rm = Resource_Manager.__new__(Resource_Manager)  # skip the API-key setup
        rm.itemsapi = SimpleNamespace(post_item_with_http_info=lambda body: (
            posted.append(body) or (None, 201, {"Location": "https://eln/api/v2/items/615"})))
        assert rm.create_item_from_template(2) == 615
        assert posted == [{"template": 2}]


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
