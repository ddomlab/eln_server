"""
What the scanner page does to bottles that are already in the ELN, now that each
bottle's place and amount live in its storage entry (an eLabFTW "container").
"""

from typing import Any

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
