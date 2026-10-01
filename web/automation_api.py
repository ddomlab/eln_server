"""
API endpoints for the backend automations (peroxide checks).

Authentication: the caller passes their own eLabFTW API key in the Authorization
header (or the apiKey cookie from the web UI); all ELN operations run as that
key. The systemd timer client in client/ calls these endpoints on a schedule
with a key placed on its host machine.
"""

import traceback

from flask import Blueprint, jsonify

import automations.peroxides.check_peroxides as check_peroxides
import automations.slackbot as slackbot
from web.auth import rm

automation_bp = Blueprint("automation", __name__, url_prefix="/api")


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
        tb = "".join(traceback.format_exception(e)).strip()
        slackbot.send_message(
            f"Error in check_peroxides: {e!r}\n```{tb[-2500:]}```",
            channel=slackbot.PEROXIDE_CHANNEL,
        )
        return jsonify({"status": "error", "error": repr(e)}), 500
    return jsonify({"status": "ok", "matches": {c: len(m) for c, m in results.items()}})
