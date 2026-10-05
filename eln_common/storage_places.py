"""
Adds storage places (cabinets, shelves...) without making near-duplicates.

eLabFTW saves any name, so "Flammable cabinet", "flammable cabinet" and
"Flamable cabinet" would become three places and split the bottles between them.
A new place is therefore compared with the places already in the same room or
place: the same name is refused (use the existing one), a similar name needs the
user's confirmation. Places are only added inside an existing one; new rooms are
added in eLabFTW by an admin.
"""

import difflib
import re
from typing import Any

from eln_common.resourcemanage import Resource_Manager

MAX_NAME_LENGTH = 255  # eLabFTW's storage_units.name column
SIMILAR_RATIO = 0.8    # difflib ratio from which two names count as "did you mean"


class PlaceClash(Exception):
    """A place with the same (exact) or a similar name exists in the same parent."""

    def __init__(self, existing: dict[str, Any], exact: bool):
        self.existing = existing
        self.exact = exact
        super().__init__(f"Already exists: {existing['name']}" if exact
                         else f"Did you mean {existing['name']}?")


class UnknownParent(Exception):
    """The room or place to add into does not exist."""


def clean_name(name: str) -> str:
    """The name with surrounding and repeated spaces removed."""
    return " ".join(name.split())


def _key(name: str) -> str:
    return clean_name(name).casefold()


def find_clash(name: str, parent_id: int, units: list[dict[str, Any]]) -> PlaceClash | None:
    """The place in the same parent with the same name (ignoring case and spaces), or failing
    that the most similar one. Names with different numbers ("Shelf 1", "Shelf 2") are not similar."""
    siblings = [u for u in units if u.get("parent_id") == parent_id]
    for unit in siblings:
        if _key(unit["name"]) == _key(name):
            return PlaceClash(unit, exact=True)
    best, best_ratio = None, SIMILAR_RATIO
    for unit in siblings:
        if re.findall(r"\d+", unit["name"]) != re.findall(r"\d+", name):
            continue
        ratio = difflib.SequenceMatcher(None, _key(unit["name"]), _key(name)).ratio()
        if ratio >= best_ratio:
            best, best_ratio = unit, ratio
    return PlaceClash(best, exact=False) if best else None


def create_place_safely(rm: Resource_Manager, name: str, parent_id: int,
                        confirm_similar: bool = False) -> dict[str, Any]:
    """
    Creates a storage place inside parent_id, unless one with the same name is there
    already, or a similar one is there and the user has not confirmed.
        :raises ValueError: the name is empty or too long.
        :raises UnknownParent: no storage place has id parent_id.
        :raises PlaceClash: a place with the same or a similar name exists there.
        :return: The new place as {id, name, parent_id, full_path}.
    """
    name = clean_name(name)
    if not name:
        raise ValueError("The place needs a name")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"The name is longer than {MAX_NAME_LENGTH} characters")
    units = rm.get_storage_units()
    parent = next((u for u in units if u["id"] == parent_id), None)
    if parent is None:
        raise UnknownParent(f"No storage place #{parent_id}")
    clash = find_clash(name, parent_id, units)
    if clash and (clash.exact or not confirm_similar):
        raise clash
    new_id = rm.create_storage_unit(name, parent_id)
    return {"id": new_id, "name": name, "parent_id": parent_id,
            "full_path": f"{parent.get('full_path') or parent['name']} > {name}"}
