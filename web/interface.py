import json
import threading
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from flask_cors import cross_origin

import automations.autofill as autofill
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


@interface_bp.route("/add_resource_interface")
def add_resource_interface():
    return send_from_directory(current_app.static_folder, "add_resource.html")  # type: ignore


@interface_bp.route("/label_gen_interface")
def label_gen_interface():
    return send_from_directory(current_app.static_folder, "label_gen.html")  # type: ignore


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
        qr_content = "https://eln.ddomlab.org/database.php?mode=view&id=" + str(qr_content)
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
        metadata = json.loads(body["metadata"])
        if metadata["extra_fields"]["Opened"]["value"] != "":
            return jsonify({"error": f"Item {id} already marked as opened on {metadata['extra_fields']['Opened']['value']}"}), 400
        metadata["extra_fields"]["Opened"]["value"] = datetime.now().isoformat()[:10]
        rmn.change_item(id, {"metadata": json.dumps(metadata), "status": 4})
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
        metadata = json.loads(body["metadata"])
        metadata["extra_fields"]["Location"]["value"] = data.get('location', "")
        rmn.change_item(id, {"metadata": json.dumps(metadata), "status": 4})
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
        rmn.change_item(id, {"status": 5})
    return "Success", 200


@interface_bp.route('/template', methods=['GET'])
@cross_origin(origins="http://localhost:8000")
def get_template():
    cat = request.args.get('category')
    if cat is None:
        return jsonify({})
    try:
        return rm().get_items_types()[int(cat) - 1]
    except Exception as e:
        print("Error initializing Resource_Manager:", e)
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
            try:
                locs = json.loads(t["metadata"])["extra_fields"]["Location"]["options"]
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
