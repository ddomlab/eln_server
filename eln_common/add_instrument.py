"""
Adds an instrument (an eLabFTW resource) from the add-resource page.

An instrument is a category whose template has no "State" field (see
add_bottle.compound_slots). It is not stored or used up, so unlike a bottle it has
no compound, storage place or amount: just a name and its template's fields.

If its "Maintenance interval" is not "None", the instrument gets a tag such as
"Maintenance: every 6 months" and its first maintenance step right away, due one
interval from today (the rules are in automations/routine_checks.yaml). There is
no "Mark open" for instruments, so nothing else starts the reminders.

Like a bottle, once the instrument exists it is never deleted: a later step that
fails is reported back as a problem, so the user can finish it in eLabFTW.
"""

import json
from datetime import date
from typing import Any

from eln_common import routine_checks
from eln_common.add_bottle import InvalidBottle, compound_slots
from eln_common.resourcemanage import Resource_Manager

INTERVAL_FIELD = "Maintenance interval"
NO_MAINTENANCE = "None"


def is_instrument(rm: Resource_Manager, category: Any) -> bool:
    """Whether the category is an instrument one (its template has no State field).
    False for anything that isn't a category, so the bottle code reports that."""
    if not isinstance(category, int) or isinstance(category, bool):
        return False
    try:
        template = rm.get_items_type(category)
    except Exception:
        return False
    extra_fields = json.loads(template.get("metadata") or "{}").get("extra_fields", {})
    return compound_slots(extra_fields) is None


def maintenance_tag(interval: Any) -> str | None:
    """The tag for a Maintenance interval value ("Every 6 months" -> "Maintenance: every
    6 months"), or None when the instrument needs no maintenance."""
    interval = str(interval or "").strip()
    if interval in ("", NO_MAINTENANCE):
        return None
    return f"Maintenance: {interval.lower()}"


def check_request(rm: Resource_Manager, data: dict[str, Any]) -> dict[str, Any]:
    """
    Checks everything the instrument needs before anything is created, so a bad
    request leaves nothing behind.
        :raises InvalidBottle: with a message for the user.
        :return: The cleaned request, the template's metadata and the maintenance rule.
    """
    category = data.get("category")
    if not is_instrument(rm, category):
        raise InvalidBottle("Choose an instrument category")
    metadata = json.loads(rm.get_items_type(category).get("metadata") or "{}")
    extra_fields = metadata.get("extra_fields", {})

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise InvalidBottle("The instrument needs a name")

    fields = data.get("fields") or {}
    if not isinstance(fields, dict):
        raise InvalidBottle("fields must be an object of field name: value")
    for name, value in fields.items():
        if name not in extra_fields:
            raise InvalidBottle(f"'{name}' is not a field of this category")
        if value is not None and not isinstance(value, (str, int, float)):
            raise InvalidBottle(f"'{name}' must be text or a number")

    # a field left out keeps the template's value (e.g. Maintenance interval "None")
    def value(name: str) -> str:
        return str(fields.get(name, extra_fields[name].get("value")) or "").strip()

    for name, field in extra_fields.items():
        if field.get("required") and not value(name):
            raise InvalidBottle(f"{name} is required")

    rule = None
    tag = maintenance_tag(value(INTERVAL_FIELD)) if INTERVAL_FIELD in extra_fields else None
    if tag:
        rule = routine_checks.rule_for(tag)
        if rule is None:
            raise InvalidBottle(f"'{value(INTERVAL_FIELD)}' is not a maintenance interval the app knows; "
                                "choose one from the list")

    return {"category": category, "title": title.strip(), "fields": fields,
            "metadata": metadata, "rule": rule}


def instrument_metadata(metadata: dict[str, Any], fields: dict[str, Any]) -> str:
    """The template's metadata with the user's values filled in."""
    extra_fields = dict(metadata.get("extra_fields", {}))
    for name, value in fields.items():
        extra_fields[name] = {**extra_fields[name], "value": "" if value is None else str(value)}
    return json.dumps({**metadata, "extra_fields": extra_fields})


def create_instrument(rm: Resource_Manager, data: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """
    Creates one instrument from a request like
        {"category": 1, "title": "Vacuum pump",
         "fields": {"Room": "3053", "Maintenance interval": "Every 6 months"}}
        :raises InvalidBottle: nothing was created.
        :raises Exception: the instrument could not be created (nothing was created).
        :return: {"bottles": [{"id", "tags", "next_due", "problems"}], "problems": []}, the
            same shape as create_bottles, so the page shows the result the same way.
    """
    request = check_request(rm, data)
    item_id = rm.create_item_from_template(request["category"])
    problems = []

    try:
        rm.change_item(item_id, {
            "title": request["title"],
            "metadata": instrument_metadata(request["metadata"], request["fields"]),
        })
    except Exception as e:
        problems.append(f"Saving the name and details failed: {e}")

    tags, next_due = [], None
    rule = request["rule"]
    if rule:
        try:
            rm.add_tag(item_id, rule["tag"])
            tags.append(rule["tag"])
        except Exception as e:
            problems.append(f"Adding the tag '{rule['tag']}' failed: {e}")
        try:
            next_due = routine_checks.schedule(rm, item_id, rule, today or date.today()).isoformat()
        except Exception as e:
            problems.append(f"Adding the maintenance step failed: {e}")

    return {"bottles": [{"id": item_id, "tags": tags, "next_due": next_due, "problems": problems}],
            "problems": []}
