"""
API endpoints for the backend automations (autofill, peroxide checks).

Authentication: the caller passes their own eLabFTW API key in the Authorization
header (or the apiKey cookie from the web UI); all ELN operations run as that
key. The systemd timer client in client/ calls these endpoints on a schedule
with a key placed on its host machine.
"""

from flask import Blueprint, jsonify, request

import automations.autofill
import automations.peroxides.check_peroxides as check_peroxides
import automations.slackbot as slackbot
from web.auth import rm

automation_bp = Blueprint("automation", __name__, url_prefix="/api")


@automation_bp.route('/autofill', methods=['POST'])
def autofill():
    """
    Runs the autofill pass (label upload, PubChem info fill, RDKit image).
    JSON body (all optional): id, start, end, force, info, label, image, size.
    If "id" is given, only that item is processed; otherwise the most recent
    `size` items with id >= start are, matching the old main.py cron behavior.
    """
    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    data = request.get_json(silent=True) or {}
    kwargs = dict(
        force=bool(data.get("force", False)),
        info=bool(data.get("info", True)),
        label=bool(data.get("label", True)),
        image=bool(data.get("image", True)),
    )
    try:
        if "id" in data:
            automations.autofill.autofill_item(rmn, int(data["id"]), **kwargs)
        else:
            automations.autofill.autofill(
                rmn,
                start=int(data.get("start", 0)),
                end=int(data["end"]) if data.get("end") is not None else None,
                size=int(data.get("size", 5)),
                **kwargs,
            )
    except Exception as e:
        # report failures to the bot channel like the old cron job did
        slackbot.send_message(f"Error in autofill: {str(e)}", channel=slackbot.ERROR_CHANNEL)
        return jsonify({"status": "error", "error": str(e)}), 500
    return jsonify({"status": "ok"})


@automation_bp.route('/check_peroxides', methods=['POST'])
def peroxide_check():
    """
    Checks the inventory against the class A-D peroxide former lists and sends
    Slack reminders for any matches.
    """
    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    try:
        results = check_peroxides.check_all_classes(rmn)
    except Exception as e:
        slackbot.send_message(f"Error in check_peroxides: {e}", channel=slackbot.PEROXIDE_CHANNEL)
        return jsonify({"status": "error", "error": str(e)}), 500
    return jsonify({"status": "ok", "matches": {c: len(m) for c, m in results.items()}})
