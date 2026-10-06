"""
What the scanner page does to bottles that are already in the ELN, now that each
bottle's place and amount live in its storage entry (an eLabFTW "container"),
and routine checks (e.g. peroxide tests) are steps on the bottle (see routine_checks).
"""

import json
from datetime import date
from typing import Any

from eln_common import routine_checks
from eln_common.resourcemanage import Resource_Manager


class UnknownPlace(Exception):
    """There is no storage place with that id."""


def storage_entry(rm: Resource_Manager, item_id: int) -> dict[str, Any]:
    """
    The bottle's one storage entry.
        :raises ValueError: with a message for the user when the bottle has no storage
            entry or more than one (those are sorted out in eLabFTW by hand).
    """
    containers = rm.get_item(item_id).get("containers") or []
    if not containers:
        raise ValueError(f"#{item_id} has no place yet: add its place and amount in eLabFTW")
    if len(containers) > 1:
        raise ValueError(f"#{item_id} is in {len(containers)} places: move it in eLabFTW")
    return containers[0]


def move_bottles(rm: Resource_Manager, ids: list[int], storage_id: int) -> dict[str, Any]:
    """
    Moves each bottle's storage entry to another place (its amount stays). Unlike the old
    Location field, moving no longer marks the bottle as opened.
        :raises UnknownPlace: no storage place has that id (nothing is moved).
        :return: {"moved": [ids], "place": the place's full path, "problems": [messages]}
    """
    places = {u["id"]: u for u in rm.get_storage_units()}
    if storage_id not in places:
        raise UnknownPlace(f"There is no storage place #{storage_id}")
    moved, problems = [], []
    for item_id in ids:
        try:
            entry = storage_entry(rm, item_id)
            rm.move_container(item_id, entry["id"], storage_id)
            moved.append(item_id)
        except ValueError as e:
            problems.append(str(e))
        except Exception as e:
            problems.append(f"#{item_id}: moving failed: {e}")
    return {"moved": moved, "place": places[storage_id].get("full_path") or places[storage_id]["name"],
            "problems": problems}


def mark_open(rm: Resource_Manager, ids: list[int], open_status: int,
              today: date | None = None) -> dict[str, Any]:
    """
    Marks each bottle as opened today (its Opened field and status) and, if it has a
    routine check (e.g. tag "Peroxide former: B"), adds the first check step.
        :return: {"opened": [ids], "checks": [{id, step, due}], "problems": [messages]}
    """
    today = today or date.today()
    opened, checks, problems = [], [], []
    for item_id in ids:
        try:
            item = rm.get_item(item_id)
            metadata = json.loads(item.get("metadata") or "{}")
            field = metadata.get("extra_fields", {}).get("Opened")
            if field is None:
                problems.append(f"#{item_id} has no 'Opened' field (its category's template needs one)")
                continue
            if field.get("value"):
                problems.append(f"#{item_id} was already marked open on {field['value']}")
                continue
            field["value"] = today.isoformat()
            rm.change_item(item_id, {"metadata": json.dumps(metadata), "status": open_status})
            opened.append(item_id)
        except Exception as e:
            problems.append(f"#{item_id}: marking it open failed: {e}")
            continue
        rule = routine_checks.rule_for(item.get("tags"))
        if rule and not routine_checks.open_check_steps(rm.get_steps(item_id)):
            try:
                due = routine_checks.schedule(rm, item_id, rule, today)
                checks.append({"id": item_id, "step": rule["step"], "due": due.isoformat()})
            except Exception as e:
                problems.append(f"#{item_id} is marked open, but adding its check '{rule['step']}' failed: {e}")
    return {"opened": opened, "checks": checks, "problems": problems}


def mark_tested(rm: Resource_Manager, ids: list[int], today: date | None = None) -> dict[str, Any]:
    """
    Records that each bottle's routine check was done today: ticks its open check step
    and adds the next one, due `every_months` from today.
        :return: {"tested": [{id, step, next_due}], "problems": [messages]}
    """
    today = today or date.today()
    tested, problems = [], []
    for item_id in ids:
        try:
            item = rm.get_item(item_id)
            rule = routine_checks.rule_for(item.get("tags"))
            if rule is None:
                problems.append(f"#{item_id} has no routine check (no tag like 'Peroxide former: B')")
                continue
            opened = json.loads(item.get("metadata") or "{}").get("extra_fields", {}).get("Opened", {})
            if not opened.get("value"):
                problems.append(f"#{item_id} is not marked open yet: use Mark Open first")
                continue
            for step in routine_checks.open_check_steps(rm.get_steps(item_id)):
                rm.finish_step(item_id, step["id"])
            due = routine_checks.schedule(rm, item_id, rule, today)
            tested.append({"id": item_id, "step": rule["step"], "next_due": due.isoformat()})
        except Exception as e:
            problems.append(f"#{item_id}: recording the test failed: {e}")
    return {"tested": tested, "problems": problems}


def mark_empty(rm: Resource_Manager, ids: list[int], empty_status: int,
               today: date | None = None) -> dict[str, Any]:
    """
    Marks each bottle as used up: its status becomes Empty, the amount in its storage
    entries 0 (so eLabFTW's inventory no longer counts it), and any open routine-check
    step is closed with a note (ticked, not deleted). The bottle and its place stay on
    record.
        :return: {"emptied": [ids], "problems": [messages]}
    """
    today = today or date.today()
    emptied, problems = [], []
    for item_id in ids:
        try:
            rm.change_item(item_id, {"status": empty_status})
        except Exception as e:
            problems.append(f"#{item_id}: marking it empty failed: {e}")
            continue
        try:
            for entry in rm.get_item(item_id).get("containers") or []:
                rm.set_container_amount(item_id, entry["id"], 0)
            for step in routine_checks.open_check_steps(rm.get_steps(item_id)):
                rm.set_step(item_id, step["id"], {
                    "body": f"{step['body']}: closed, bottle marked empty on {today.isoformat()} (no test needed)"})
                rm.finish_step(item_id, step["id"])
            emptied.append(item_id)
        except Exception as e:
            problems.append(f"#{item_id} is marked Empty, but setting its amount to 0 or closing its check failed: {e}")
    return {"emptied": emptied, "problems": problems}
