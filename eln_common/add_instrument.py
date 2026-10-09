"""
Adds an instrument (an eLabFTW resource) from the add-resource page.

An instrument is a category whose template has no "State" field (see
add_bottle.compound_slots). It is not stored or used up, so unlike a bottle it has
no compound, storage place or amount: just a name, its template's fields and,
optionally, a maintenance procedure for its main text.

If "Maintenance every" is filled in (a whole number, with "Maintenance unit" days,
weeks or months), the instrument gets a tag such as "Maintenance: every 45 days"
and its first maintenance step right away, due one interval from today (see
routine_checks.maintenance_rule). There is no "Mark open" for instruments, so
nothing else starts the reminders.

Like a bottle, once the instrument exists it is never deleted: a later step that
fails is reported back as a problem, so the user can finish it in eLabFTW.
"""

import html
import json
import re
from datetime import date
from typing import Any

from eln_common import routine_checks
from eln_common.add_bottle import InvalidBottle, compound_slots
from eln_common.resourcemanage import Resource_Manager

EVERY_FIELD = "Maintenance every"
UNIT_FIELD = "Maintenance unit"
UNITS = {"days": "day", "weeks": "week", "months": "month"}  # the template's options -> the tag's unit
PROCEDURE_HEADING = "Maintenance procedure"
MAX_PROCEDURE = 20000  # characters


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


def maintenance_rule(every: str, unit: str) -> dict[str, Any] | None:
    """
    The maintenance check for the form's "Maintenance every" and "Maintenance unit"
    values; None when "every" is empty (no maintenance).
        :raises InvalidBottle: when they can't make an interval.
    """
    if every == "":
        return None
    if not re.fullmatch(r"\d+", every) or int(every) < 1:
        raise InvalidBottle(f"{EVERY_FIELD} must be a whole number, 1 or more (or empty for no maintenance)")
    if unit == "":
        raise InvalidBottle(f"Choose the {UNIT_FIELD} ({', '.join(UNITS)}) for Maintenance every {every}")
    if unit not in UNITS:
        raise InvalidBottle(f"{UNIT_FIELD} must be one of: {', '.join(UNITS)}")
    rule = routine_checks.maintenance_rule(routine_checks.maintenance_tag(int(every), UNITS[unit]))
    if rule is None:
        longest = routine_checks.MAX_EVERY[UNITS[unit]]
        raise InvalidBottle(f"Maintenance every {every} {unit} is too long: at most {longest} {unit}")
    return rule


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

    # a field left out keeps the template's value (e.g. Maintenance unit "months")
    def value(name: str) -> str:
        return str(fields.get(name, extra_fields.get(name, {}).get("value")) or "").strip()

    for name, field in extra_fields.items():
        if field.get("required") and not value(name):
            raise InvalidBottle(f"{name} is required")

    rule = None
    if EVERY_FIELD in extra_fields:
        # the unit must be chosen, not taken from the template: "45" meant as days must
        # never become 45 months because the dropdown was left alone
        rule = maintenance_rule(value(EVERY_FIELD), str(fields.get(UNIT_FIELD) or "").strip())

    procedure = data.get("procedure") or ""
    if not isinstance(procedure, str):
        raise InvalidBottle("The maintenance procedure must be text")
    if len(procedure) > MAX_PROCEDURE:
        raise InvalidBottle(f"The maintenance procedure is too long (at most {MAX_PROCEDURE} characters); "
                            "add the rest in eLabFTW")

    return {"category": category, "title": title.strip(), "fields": fields,
            "metadata": metadata, "rule": rule, "procedure": procedure.strip()}


def instrument_metadata(metadata: dict[str, Any], fields: dict[str, Any]) -> str:
    """The template's metadata with the user's values filled in."""
    extra_fields = dict(metadata.get("extra_fields", {}))
    for name, value in fields.items():
        extra_fields[name] = {**extra_fields[name], "value": "" if value is None else str(value)}
    return json.dumps({**metadata, "extra_fields": extra_fields})


def procedure_html(procedure: str) -> str:
    """The main text for a typed procedure: the heading, then a paragraph per block of
    lines (a blank line starts a new one). The text is escaped, so it shows as typed."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", procedure.replace("\r\n", "\n")) if p.strip()]
    body = "\n".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs)
    return f"<h2>{PROCEDURE_HEADING}</h2>\n{body}"


def create_instrument(rm: Resource_Manager, data: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """
    Creates one instrument from a request like
        {"category": 1, "title": "Vacuum pump", "procedure": "1. Switch off...",
         "fields": {"Room": "3053", "Maintenance every": "45", "Maintenance unit": "days"}}
        :raises InvalidBottle: nothing was created.
        :raises Exception: the instrument could not be created (nothing was created).
        :return: {"bottles": [{"id", "tags", "next_due", "problems"}], "problems": []}, the
            same shape as create_bottles, so the page shows the result the same way.
    """
    request = check_request(rm, data)
    item_id = rm.create_item_from_template(request["category"])
    problems = []

    changes = {"title": request["title"],
               "metadata": instrument_metadata(request["metadata"], request["fields"])}
    if request["procedure"]:  # otherwise the template's main text (the empty heading) stays
        changes["body"] = procedure_html(request["procedure"])
    try:
        rm.change_item(item_id, changes)
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
