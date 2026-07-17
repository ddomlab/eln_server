import json
import threading
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from flask_cors import cross_origin

import automations.autofill as autofill
import eln_common.config as config
from eln_common.resourcemanage import Resource_Manager
import web.label_creating as label_creating
import web.print_handling as print_handling
import web.search_process as search_process
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
    return send_from_directory(current_app.static_folder, "add_resource.html")  # type: ignore


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
    if icon == "QR Code":
        icon = None
    if icon == "None":
        icon = None
    label_creating.print_label(
        caption=title,
        longcaption=text,
        icon=icon,
        codecontent=qr_content,
        height=height
    )
    return send_from_directory(current_app.static_folder, "print.pdf")  # type: ignore


@interface_bp.route('/search', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def search():
    data = request.get_json(force=True)  # Parse JSON from body
    CAS = data.get('CAS')
    template = data.get('template')

    print("Search query:", CAS)
    try:
        results = search_process.search_and_fill(template, CAS)
    except ValueError as e:
        print("Error in search_and_fill:", e)
        return jsonify({"error": str(e)}), 400
    print("Results:", results)
    return jsonify(results)


@interface_bp.route('/print', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def print_registry():
    data = request.get_json()
    ids = data.get('id', [])
    if len(ids) == 0:
        return jsonify({"error": "No IDs provided"}), 400
    if not isinstance(ids, list):
        return jsonify({"error": "Expected a list of IDs"}), 400

    print_handling.add_item(rm(), [int(x) for x in ids])
    print("Printing items with IDs:", ids)

    return send_from_directory(current_app.static_folder, "print.pdf")  # type: ignore


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


@interface_bp.route('/change_location', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def change_location():
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
        location = metadata.get("extra_fields", {}).get("Location")
        if location is None:
            return jsonify({"error": f"Item {id} has no 'Location' extra field. "
                            "Its category's template must define an extra field named "
                            "'Location' (exact spelling) before its location can be set."}), 400
        location["value"] = data.get('location', "")
        rmn.change_item(id, {"metadata": json.dumps(metadata), "status": config.setting("status_open", 4)})
    return "Success", 200


@interface_bp.route('/mark_empty', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def mark_empty():
    data = request.get_json()
    ids = data.get('id', [])
    if len(ids) == 0:
        return jsonify({"error": "No IDs provided"}), 400
    rmn = rm()
    if not isinstance(ids, list):
        return jsonify({"error": "Expected a list of IDs"}), 400
    for id in ids:
        rmn.change_item(id, {"status": config.setting("status_empty", 5)})
    return "Success", 200


@interface_bp.route('/template', methods=['GET'])
@cross_origin(origins="http://localhost:8000")
def get_template():
    cat = request.args.get('category')
    if cat is None:
        return jsonify({})
    try:
        # match on the category's id -- list position is not stable across
        # instances (or across deleting/reordering categories)
        rmn = rm()
        types = rmn.get_items_types()
        template = next((t for t in types if int(t["id"]) == int(cat)), None)
        if template is None:
            return jsonify({"status": "error", "error": f"No resource category with id {cat}"}), 404
        if "metadata" not in template:
            # eLabFTW >= 5.6 omits metadata from the items_types listing;
            # the client needs it to build the form, so fetch the full type
            template = rmn.get_items_type(int(cat))
        return template
    except Exception as e:
        print("Error initializing Resource_Manager:", e)
        return jsonify({"status": "error", "error": str(e)}), 400


@interface_bp.route('/add_option', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def add_option():
    """Appends an option to a select extra field in a category's template, so
    a value typed under "Other" becomes a real choice for future resources.
    Expects {category, field, option}. Note eLabFTW only lets team admins edit
    templates, so this fails with the eLN's error for everyone else."""
    data = request.get_json(force=True)
    field = data.get('field')
    option = str(data.get('option') or "").strip()
    try:
        category = int(data.get('category'))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "error": "Invalid category id"}), 400
    if not field or not option:
        return jsonify({"status": "error", "error": "Both 'field' and 'option' are required"}), 400

    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401

    try:
        template = rmn.get_items_type(category)
        metadata = json.loads(template.get("metadata") or "{}")
        field_def = metadata.get("extra_fields", {}).get(field)
        if field_def is None:
            return jsonify({"status": "error",
                            "error": f"Category {category} has no extra field named '{field}'"}), 404
        if field_def.get("type") != "select":
            return jsonify({"status": "error",
                            "error": f"Field '{field}' is not a select field"}), 400
        options = field_def.setdefault("options", [])
        if option not in options:
            options.append(option)
            rmn.change_items_type(category, {"metadata": json.dumps(metadata)})
        return jsonify({"status": "ok", "options": options})
    except Exception as e:
        print("Error adding option to template:", e)
        return jsonify({"status": "error", "error": str(e)}), 400


def _autofill_in_background(rmn: Resource_Manager, item_id: int):
    """Runs the autofill steps on a newly created item without blocking the response."""
    def target():
        try:
            autofill.autofill_item(rmn, item_id)
        except Exception as e:
            print(f"Error autofilling new item {item_id}:", e)
    threading.Thread(target=target, daemon=True).start()


@interface_bp.route('/add_resource', methods=['POST'])
@cross_origin(origins="http://localhost:8000")
def add_resource():
    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            raise ValueError("Expected top-level JSON object")

        resource = search_process.dict_complexify(data)
        try:
            rmn = rm()
            item_id = rmn.create_item(data['category'], resource)
            # kick off autofill (label, info, image) for the new resource immediately
            _autofill_in_background(rmn, item_id)
            return jsonify({"status": "ok", "received": data, "id": item_id})
        except Exception as e:
            print("Error Initializing Resource Manager:", e)
            return jsonify({"status": "error", "error": str(e)}), 400

    except Exception as e:  # send all errors to the client
        print("Error parsing submission:", e)
        return jsonify({"status": "error", "error": str(e)}), 400


@interface_bp.route('/get_locations', methods=['GET'])
@cross_origin(origins="http://localhost:8000")
def get_locations():
    try:
        rmn = rm()
        types = rmn.get_items_types()
        locations = []
        for t in types:
            if "metadata" not in t:
                # eLabFTW >= 5.6 omits metadata from the items_types listing
                t = rmn.get_items_type(t["id"])
            try:
                locs = json.loads(t["metadata"] or "{}")["extra_fields"]["Location"]["options"]
            except KeyError:
                locs = []
            # Add only unique locations
            for loc in locs:
                if loc not in locations:
                    locations.append(loc)
        return jsonify(locations)
    except Exception as e:
        print("Error getting locations:", e)
        return jsonify({"status": "error", "error": str(e)}), 400
