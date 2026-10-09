"""
API endpoints for the backend automations (peroxide checks, routine-check reminders).

Authentication: the caller passes their own eLabFTW API key in the Authorization
header (or the apiKey cookie from the web UI); all ELN operations run as that
key. The systemd timer client in client/ calls these endpoints on a schedule
with a key placed on its host machine.
"""

import traceback
from datetime import date

from flask import Blueprint, jsonify, request

import automations.peroxides.check_peroxides as check_peroxides
import automations.slackbot as slackbot
import eln_common.config as config
import eln_common.routine_checks as routine_checks
from web.auth import rm

automation_bp = Blueprint("automation", __name__, url_prefix="/api")


def _report_error(task: str, e: Exception, channel: str) -> str:
    """
    Posts an automation's error, with its traceback, to a Slack channel.
        :return: The error for the response; it also names Slack's failure if the
            report could not be posted, so a Slack problem never hides the first one.
    """
    tb = "".join(traceback.format_exception(e)).strip()
    try:
        slackbot.send_message(f"Error in {task}: {e!r}\n```{tb[-2500:]}```", channel=channel)
    except Exception as slack_error:
        return f"{e!r} (reporting it to Slack failed too: {slack_error})"
    return repr(e)


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
        return jsonify({"status": "error",
                        "error": _report_error("check_peroxides", e, slackbot.PEROXIDE_CHANNEL)}), 500
    return jsonify({"status": "ok", "matches": {c: len(m) for c, m in results.items()}})


@automation_bp.route('/routine_checks', methods=['POST'])
def routine_checks_reminder():
    """
    The monthly reminder: posts the routine checks (peroxide tests) that are overdue or
    due this month to the Slack maintenance channel. It only reads the ELN.
    Body (optional): {"dry_run": true} returns the message without posting anything;
    a dry run may also set "today": "YYYY-MM-DD" to preview another month's message.
    """
    data = request.get_json(force=True, silent=True) or {}
    dry_run = data.get("dry_run") is True
    today = date.today()
    if "today" in data:
        if not dry_run:
            return jsonify({"status": "error", "error": '"today" only works with "dry_run": true'}), 400
        try:
            today = date.fromisoformat(str(data["today"]))
        except ValueError:
            return jsonify({"status": "error", "error": '"today" must be a date like 2026-11-06'}), 400
    try:
        rmn = rm()
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 401
    try:
        bottles = routine_checks.bottles_to_check(rmn, config.setting("status_empty", 5))
        report = routine_checks.due_checks(rmn, bottles, today)
        message = routine_checks.format_report(report, today)
        if not dry_run:
            slackbot.send_message(message, channel=slackbot.MAINTENANCE_CHANNEL)
    except Exception as e:
        error = repr(e) if dry_run else _report_error("routine_checks", e, slackbot.ERROR_CHANNEL)
        return jsonify({"status": "error", "error": error}), 500
    return jsonify({"status": "ok", "sent": not dry_run, "today": today.isoformat(),
                    **{group: len(entries) for group, entries in report.items()}, "message": message})
