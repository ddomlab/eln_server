import io
import json
from datetime import datetime

from flask import Blueprint, current_app, jsonify, redirect, request, send_file, send_from_directory
from flask_cors import cross_origin
from requests import HTTPError

import eln_common.add_bottle as add_bottle
import eln_common.bottle_actions as bottle_actions
import eln_common.compound_import as compound_import
import eln_common.bottle_tags as bottle_tags
import eln_common.config as config
import eln_common.pubchem as pubchem
import eln_common.storage_places as storage_places
import web.label_creating as label_creating
import web.print_handling as print_handling
from web.auth import rm

interface_bp = Blueprint("interface", __name__)


@interface_bp.route('/')
def index():
    return send_from_directory(current_app.static_folder, "index.html")  # type: ignore


@interface_bp.route('/favicon.ico', methods=['GET'])
def favicon():
    return send_from_directory(current_app.static_folder, 'favicon.ico')  # type: ignore


@interface_bp.route('/ping', methods=['GET'])
def ping():
    return "pong", 200


@interface_bp.route('/eln_config', methods=['GET'])
def eln_config():
    """Non-secret instance settings the static web UI needs (e.g. where the
    eLabFTW web interface lives, for building/recognizing resource links)."""
    return jsonify({"eln_web_url": config.WEB_URL})


@interface_bp.route("/add_resource_interface")
def add_resource_interface():
    # the old 16-field form was replaced by the add-bottle page; keep old links working
    return redirect("/add_bottle_interface")


@interface_bp.route("/add_bottle_interface")
def add_bottle_interface():
    return send_from_directory(current_app.static_folder, "add_bottle.html")  # type: ignore


@interface_bp.route("/label_gen_interface")
def label_gen_interface():
    return send_from_directory(current_app.static_folder, "label_gen.html")  # type: ignore


@interface_bp.route("/settings_interface")
def settings_interface():
    return send_from_directory(current_app.static_folder, "settings.html")  # type: ignore


@interface_bp.route('/categories', methods=['GET'])
@cross_origin(origins="http://localhost:8000")
def get_categories():
    """The team's resource categories as [{id, title}], for UI dropdowns."""
    try:
        types = rm().get_items_types()
        return jsonify([{"id": t["id"], "title": t["title"]} for t in types])
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


@interface_bp.route('/statuses', methods=['GET'])
@cross_origin(origins="http://localhost:8000")
def get_statuses():
    """The team's resource statuses as [{id, title}], for UI dropdowns."""
    try:
        statuses = rm().get_items_statuses()
        return jsonify([{"id": s["id"], "title": s["title"]} for s in statuses])
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


@interface_bp.route('/compounds_list', methods=['GET'])
@cross_origin(origins="http://localhost:8000")
def compounds_list():
    """Existing compounds as [{id, name, cas, formula, hazards, peroxide_class}], sorted
    by name, for the add-bottle compound dropdown. hazards and peroxide_class are what
    the bottle's tags will be (see bottle_tags)."""
    try:
        compounds = rm().get_compounds()
        listing = [
            {
                "id": c["id"],
                "name": c.get("name") or "",
                "cas": c.get("cas_number") or "",
                "formula": c.get("molecular_formula") or "",
                "hazards": [tag for flag, tag in bottle_tags.HAZARD_TAGS.items() if c.get(flag)],
                "peroxide_class": bottle_tags.peroxide_class(c),
            }
            for c in compounds
        ]
        return jsonify(sorted(listing, key=lambda c: c["name"].lower()))
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


@interface_bp.route('/bottle_form', methods=['GET'])
@cross_origin(origins="http://localhost:8000")
def bottle_form():
    """What the add-bottle page needs to draw its form: each bottle category with the
    compounds to pick (compound_slots) and the extra fields that stay on the bottle
    (in template order), plus eLabFTW's units and the units offered per State."""
    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    try:
        categories = []
        for t in rmn.get_items_types():
            metadata = json.loads(rmn.get_items_type(t["id"]).get("metadata") or "{}")
            extra_fields = metadata.get("extra_fields", {})
            slots = add_bottle.compound_slots(extra_fields)
            if slots is None:
                continue
            fields = add_bottle.bottle_fields(extra_fields, bool(slots))
            categories.append({
                "id": t["id"],
                "title": t["title"],
                "compound_slots": slots,
                "fields": [{"name": name, **field} for name, field in
                           sorted(fields.items(), key=lambda kv: kv[1].get("position", 0))],
            })
        return jsonify({"categories": categories, "units": add_bottle.UNITS,
                        "units_by_state": add_bottle.UNITS_BY_STATE})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


def _pubchem_preview(pc: dict) -> dict:
    """The PubChem fields the page shows before the user confirms an import."""
    return {
        "cid": pc.get("pubchem_cid"),
        "name": pc.get("name") or "",
        "cas": pc.get("cas_number") or "",
        "formula": pc.get("molecular_formula") or "",
        "molecular_weight": pc.get("molecular_weight"),
        "smiles": pc.get("smiles") or "",
    }


@interface_bp.route('/compounds/pubchem', methods=['GET'])
@cross_origin(origins="http://localhost:8000")
def compounds_pubchem():
    """Read-only PubChem lookup by ?cas= or ?name=. Saves nothing. For each match
    (at most 5) says which ELN compound, if any, it already corresponds to."""
    cas = (request.args.get('cas') or '').strip()
    name = (request.args.get('name') or '').strip()
    if not cas and not name:
        return jsonify({"status": "error", "error": "Give a CAS number or a name"}), 400
    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    try:
        found = pubchem.search(cas=cas or None, name=None if cas else name)
        if not found:
            return jsonify({"status": "error", "error": "No match in PubChem"}), 404
        compounds = rmn.get_all_compounds()
        candidates = []
        for pc in found:
            clash = compound_import.find_clash(pc, cas or None, compounds)
            candidates.append({
                "pubchem": _pubchem_preview(pc),
                "existing": compound_import.summary(clash.existing) if clash else None,
                "reason": clash.reason if clash else "",
                "can_restore": clash.can_restore if clash else False,
            })
        return jsonify({"candidates": candidates})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 502


@interface_bp.route('/compounds', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def create_compound():
    """Creates a compound from PubChem: {cid, cas}. The details and hazard pictograms
    are fetched again here from PubChem rather than trusted from the page. 409 with
    the existing compound if the ELN already has it; when that is a deleted compound
    (can_restore), sending {cid, cas, restore: <its id>} restores and refreshes it (200)."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        cid = int(data.get('cid'))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "error": "Missing or invalid PubChem ID (cid)"}), 400
    cas = (data.get('cas') or '').strip() or None
    if cas and not pubchem.check_if_cas(cas):
        return jsonify({"status": "error", "error": f"'{cas}' is not a valid CAS number"}), 400
    restore_id = data.get('restore')
    if restore_id is not None and (not isinstance(restore_id, int) or isinstance(restore_id, bool)):
        return jsonify({"status": "error", "error": "restore must be a compound id"}), 400
    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    try:
        found = pubchem.fetch(cid)
        if not found:
            return jsonify({"status": "error", "error": f"PubChem has no compound {cid}"}), 404
        saved = compound_import.create_compound_safely(rmn, found, cas, restore_id)
    except compound_import.CompoundClash as e:
        return jsonify({"status": "error", "error": f"Already in the ELN ({e.reason})",
                        "existing": compound_import.summary(e.existing),
                        "can_restore": e.can_restore}), 409
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
    result = compound_import.summary(saved)
    result["restored"] = saved["id"] == restore_id
    # None: PubChem has no hazard classification, so the page asks the user to check the SDS
    result["pictograms"] = found["pictograms"]
    return jsonify(result), 200 if result["restored"] else 201


def _place(unit: dict) -> dict:
    """A storage place as the page uses it."""
    return {
        "id": unit["id"],
        "name": unit["name"],
        "parent_id": unit.get("parent_id"),
        "full_path": unit.get("full_path") or unit["name"],
    }


@interface_bp.route('/storage_tree', methods=['GET'])
@cross_origin(origins="http://localhost:8000")
def storage_tree():
    """Storage places as [{id, name, parent_id, full_path}], for the
    Room -> Place dropdowns (rooms have parent_id null)."""
    try:
        return jsonify([_place(u) for u in rm().get_storage_units()])
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


@interface_bp.route('/storage_units', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def create_storage_unit():
    """Adds a storage place inside an existing one: {name, parent_id, confirm}.
    201 with the new place; 409 with the existing place when one in the same parent
    has the same name (exact: true) or a similar one (exact: false; send again with
    confirm: true to add it anyway). New rooms are added in eLabFTW, not here."""
    data = request.get_json(force=True, silent=True) or {}
    name = data.get('name')
    parent_id = data.get('parent_id')
    if not isinstance(name, str):
        return jsonify({"status": "error", "error": "The place needs a name"}), 400
    if not isinstance(parent_id, int) or isinstance(parent_id, bool):
        return jsonify({"status": "error",
                        "error": "Choose the room or place to add it in (parent_id)"}), 400
    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    try:
        place = storage_places.create_place_safely(rmn, name, parent_id, data.get('confirm') is True)
    except storage_places.PlaceClash as e:
        return jsonify({"status": "error", "error": str(e), "exact": e.exact,
                        "existing": _place(e.existing)}), 409
    except storage_places.UnknownParent as e:
        return jsonify({"status": "error", "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 400
    except HTTPError as e:
        # e.g. 403 when eLabFTW does not let this user manage storage places
        status = e.response.status_code if e.response is not None else 500
        return jsonify({"status": "error", "error": f"eLabFTW refused: {e}"}), status
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
    return jsonify(place), 201


# the team-ID settings that the web settings page may change, with their coercers
SETTINGS_SCHEMA = {
    "status_open": int,
    "status_empty": int,
    "chemical_categories": lambda v: [int(x) for x in v],
    "label_date_categories": lambda v: [int(x) for x in v],
}


@interface_bp.route('/experiments', methods=['GET'])
def get_experiments():
    """Experiments matching ?q= (or the most recent ones) as [{id, title}],
    for the associate-with-experiment dropdown."""
    try:
        exps = rm().search_experiments(request.args.get('q', ''))
        return jsonify([{"id": e["id"], "title": e["title"]} for e in exps])
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


@interface_bp.route('/resources', methods=['GET'])
@cross_origin(origins="http://localhost:8000")
def get_resources():
    """Resources matching ?q= (or the most recent ones) as [{id, title}],
    for the label generator's resource-ID search dropdown."""
    try:
        items = rm().search_items(request.args.get('q', ''))
        return jsonify([{"id": i["id"], "title": i["title"]} for i in items])
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


@interface_bp.route('/settings', methods=['GET', 'POST'])
@cross_origin(origins="http://localhost:8000")
def settings():
    """GET: the current team-ID settings. POST: update them in config.yaml
    (requires a working eLabFTW API key, since this changes server behavior)."""
    defaults = {"status_open": 4, "status_empty": 5,
                "chemical_categories": [2, 3], "label_date_categories": [2, 3, 4]}
    if request.method == 'GET':
        return jsonify({k: config.setting(k, d) for k, d in defaults.items()})

    try:
        if not isinstance(rm().get_items_types(), list):
            raise ValueError("API key was not accepted by the ELN")
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401

    data = request.get_json(force=True)
    try:
        updates = {k: SETTINGS_SCHEMA[k](data[k]) for k in SETTINGS_SCHEMA if k in data}
    except (TypeError, ValueError) as e:
        return jsonify({"status": "error", "error": f"Invalid value: {e}"}), 400
    if not updates:
        return jsonify({"status": "error", "error": "No known settings in request"}), 400
    config.update_settings(updates)
    return jsonify({"status": "ok", "updated": updates})


@interface_bp.route('/create_label', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def create_label():
    data = request.get_json(force=True)
    title = data.get('Title', '')
    text = data.get('Text', '')
    icon = data.get('Icon', None)
    qr_type = data.get('QRContentType', None)
    qr_content = data.get('QRContent', None)
    height = data.get('Height', 18)

    if qr_type == "Resource":
        qr_content = config.item_web_url(qr_content)
    elif qr_type == "Location":
        # a storage place's id; scanning it on the scanner page moves the scanned bottles there
        qr_content = f"STORAGE={qr_content or ''}"
    if icon == "QR Code":
        icon = None
    if icon == "None":
        icon = None
    pdf = label_creating.label_pdf(
        caption=title,
        longcaption=text,
        icon=icon,
        codecontent=qr_content,
        height=height
    )
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", download_name="label.pdf")


@interface_bp.route('/print', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def print_registry():
    """The labels for {id: [resource ids]} as one PDF, for the page to open and print."""
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get('id', [])
    if not isinstance(ids, list):
        return jsonify({"error": "Expected a list of IDs"}), 400
    if len(ids) == 0:
        return jsonify({"error": "No IDs provided"}), 400
    try:
        ids = [int(x) for x in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "IDs must be numbers"}), 400
    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"error": str(e)}), 401
    try:
        pdf = print_handling.labels_pdf(rmn, ids)
    except Exception as e:
        return jsonify({"error": f"Making the labels failed: {e}"}), 500
    print("Printing items with IDs:", ids)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", download_name="labels.pdf")


@interface_bp.route('/associate', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def associate():
    data = request.get_json()
    ids = data.get('id', [])
    exp_id = data.get('exp_id')
    if len(ids) == 0:
        return jsonify({"error": "No IDs provided"}), 400
    rmn = rm()
    if not isinstance(ids, list):
        return jsonify({"error": "Expected a list of IDs"}), 400
    for id in ids:
        rmn.experiment_item_link(exp_id, id)
    return ("Success", 200, {"exp_name": rmn.get_experiment(exp_id)["title"]})


@interface_bp.route('/mark_open', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def mark_open():
    data = request.get_json()
    ids = data.get('id', [])
    if len(ids) == 0:
        return jsonify({"error": "No IDs provided"}), 400
    rmn = rm()
    if not isinstance(ids, list):
        return jsonify({"error": "Expected a list of IDs"}), 400
    for id in ids:
        body = rmn.get_item(id)
        metadata = json.loads(body["metadata"] or "{}")
        opened = metadata.get("extra_fields", {}).get("Opened")
        if opened is None:
            return jsonify({"error": f"Item {id} has no 'Opened' extra field. "
                            "Its category's template must define an extra field named "
                            "'Opened' (exact spelling) for it to be marked as opened."}), 400
        if opened.get("value", "") != "":
            return jsonify({"error": f"Item {id} already marked as opened on {opened['value']}"}), 400
        opened["value"] = datetime.now().isoformat()[:10]
        rmn.change_item(id, {"metadata": json.dumps(metadata), "status": config.setting("status_open", 4)})
    return "Success", 200


def _id_list(data: dict) -> list[int]:
    """The resource ids in a scanner request {id: [...]}.
        :raises ValueError: with a message for a 400 answer."""
    ids = data.get('id', [])
    if not isinstance(ids, list):
        raise ValueError("Expected a list of IDs")
    if len(ids) == 0:
        raise ValueError("No IDs provided")
    try:
        return [int(x) for x in ids]
    except (TypeError, ValueError):
        raise ValueError("IDs must be numbers")


@interface_bp.route('/move_to_storage', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def move_to_storage():
    """Moves the scanned bottles to a storage place: {id: [ids], storage_id}. The scanner
    sends this when a place's QR code (STORAGE=<id>) is scanned. 200 with {moved, place,
    problems}; problems lists bottles that could not be moved and why."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        ids = _id_list(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    storage_id = data.get('storage_id')
    if not isinstance(storage_id, int) or isinstance(storage_id, bool):
        return jsonify({"error": "Scan a storage place's QR code (storage_id)"}), 400
    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"error": str(e)}), 401
    try:
        return jsonify(bottle_actions.move_bottles(rmn, ids, storage_id))
    except bottle_actions.UnknownPlace as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@interface_bp.route('/mark_empty', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def mark_empty():
    """Marks the scanned bottles as used up: {id: [ids]}. Status Empty and amount 0.
    200 with {emptied, problems}."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        ids = _id_list(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"error": str(e)}), 401
    return jsonify(bottle_actions.mark_empty(rmn, ids, config.setting("status_empty", 5)))


@interface_bp.route('/resources', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def create_resource():
    """Adds one or more identical bottles, linked to their compound(s) and put in a storage
    place: {category, title, compounds: [ids], count, storage: {place_id, amount, unit},
    fields: {name: value}}. 400 if the request is incomplete (nothing created). 409 with
    "same_lot" and a "question" for the user when bottles from that lot are already in the
    ELN; send again with confirm_same_lot: true to add them. 201 with
    {bottles: [{id, url, tags, problems}], problems} once at least one bottle exists."""
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify({"status": "error", "error": "Expected a JSON object"}), 400
    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    try:
        result = add_bottle.create_bottles(rmn, data)
    except add_bottle.InvalidBottle as e:
        return jsonify({"status": "error", "error": str(e)}), 400
    except add_bottle.SameLotBottles as e:
        return jsonify({"status": "error", "error": str(e), "question": e.question, "same_lot": [
            {**b, "url": config.item_web_url(b["id"])} for b in e.bottles]}), 409
    except Exception as e:
        return jsonify({"status": "error", "error": f"The bottle was not created: {e}"}), 500
    for bottle in result["bottles"]:
        bottle["url"] = config.item_web_url(bottle["id"])
    return jsonify(result), 201
