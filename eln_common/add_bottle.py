"""
Adds a bottle (an eLabFTW resource) the structured way.

Instead of typing every detail into the template's extra fields, a bottle now
points to things that are stored once:
  - its compound(s), which hold the name, structure and hazards;
  - a storage place, with the amount and unit (eLabFTW "containers").
Only the facts about this one bottle (supplier, lot, purity, dates...) stay as
extra fields.

create_bottle() does it in order: create from the template -> title and fields ->
link compounds -> put it in its place -> structure image. Once the bottle exists
it is never deleted: a later step that fails is reported back as a problem, so
the user can finish it in eLabFTW.
"""

import json
from typing import Any

from automations.image_generator import generate_image
from eln_common.resourcemanage import Resource_Manager

# eLabFTW's fixed list of storage units (μ is the Greek letter mu, U+03BC)
UNITS = ["•", "μL", "mL", "L", "μg", "mg", "g", "kg", "bar", "m", "e6 cells"]
# what the form offers for each State; any unit above is still accepted
UNITS_BY_STATE = {
    "Liquid": ["μL", "mL", "L"],
    "Solid": ["μg", "mg", "g", "kg"],
    "Gas": ["bar", "L", "g"],
}

# template fields that now live in Storage (place, amount and unit)...
STORAGE_FIELDS = {"Room", "Location", "Quantity"}
# ...and in the linked compounds. Bottles without compounds (polymers) keep these.
COMPOUND_FIELDS = {"Full name", "SMILES", "Molecular Weight", "Hazards Link", "Pubchem Link",
                   "Solvent SMILES"}


class InvalidBottle(Exception):
    """The request can't make a bottle (missing or unknown value); nothing was created."""


def bottle_fields(extra_fields: dict[str, Any], has_compounds: bool) -> dict[str, Any]:
    """The template's extra fields that stay on the bottle itself."""
    moved = STORAGE_FIELDS | (COMPOUND_FIELDS if has_compounds else set())
    return {name: field for name, field in extra_fields.items() if name not in moved}


def clean_unit(unit: Any) -> str:
    """The unit as eLabFTW spells it ("µL" typed with the micro sign becomes "μL")."""
    unit = str(unit or "").strip().replace("µ", "μ")
    if unit not in UNITS:
        raise InvalidBottle(f"Unknown unit '{unit}'; use one of {', '.join(UNITS)}")
    return unit


def check_request(rm: Resource_Manager, data: dict[str, Any]) -> dict[str, Any]:
    """
    Checks everything the bottle needs before anything is created, so a bad request
    leaves no half-made bottle behind.
        :raises InvalidBottle: with a message for the user.
        :return: The cleaned request plus the template's metadata to start from.
    """
    category = data.get("category")
    if not isinstance(category, int) or isinstance(category, bool):
        raise InvalidBottle("Choose a category")
    try:
        template = rm.get_items_type(category)
    except Exception:
        raise InvalidBottle(f"There is no category #{category}")

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise InvalidBottle("The bottle needs a name")

    compounds = data.get("compounds") or []
    if not isinstance(compounds, list) or not all(
            isinstance(c, int) and not isinstance(c, bool) for c in compounds):
        raise InvalidBottle("compounds must be a list of compound ids")
    live_compounds = {c["id"]: c for c in rm.get_compounds()}
    for compound_id in compounds:
        if compound_id not in live_compounds:
            raise InvalidBottle(f"There is no compound #{compound_id}")

    storage = data.get("storage")
    if not isinstance(storage, dict):
        raise InvalidBottle("Choose where the bottle is kept, with its amount")
    place_id = storage.get("place_id")
    if not isinstance(place_id, int) or isinstance(place_id, bool):
        raise InvalidBottle("Choose where the bottle is kept")
    if place_id not in {u["id"] for u in rm.get_storage_units()}:
        raise InvalidBottle(f"There is no storage place #{place_id}")
    amount = storage.get("amount")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount < 0:
        raise InvalidBottle("The amount must be a number, 0 or more")
    unit = clean_unit(storage.get("unit"))

    metadata = json.loads(template.get("metadata") or "{}")
    allowed = bottle_fields(metadata.get("extra_fields", {}), bool(compounds))
    fields = data.get("fields") or {}
    if not isinstance(fields, dict):
        raise InvalidBottle("fields must be an object of field name: value")
    for name, value in fields.items():
        if name not in allowed:
            raise InvalidBottle(f"'{name}' is not a field of this category's bottles")
        if value is not None and not isinstance(value, (str, int, float)):
            raise InvalidBottle(f"'{name}' must be text or a number")

    return {"category": category, "title": title.strip(), "compounds": compounds,
            "place_id": place_id, "amount": amount, "unit": unit, "fields": fields,
            "metadata": metadata, "smiles": live_compounds[compounds[0]].get("smiles") if compounds else None}


def bottle_metadata(metadata: dict[str, Any], fields: dict[str, Any], has_compounds: bool) -> str:
    """The template's metadata with only the bottle's own fields, filled with the user's values."""
    kept = bottle_fields(metadata.get("extra_fields", {}), has_compounds)
    for name, value in fields.items():
        kept[name] = {**kept[name], "value": "" if value is None else str(value)}
    return json.dumps({**metadata, "extra_fields": kept})


def create_bottle(rm: Resource_Manager, data: dict[str, Any]) -> dict[str, Any]:
    """
    Creates a bottle from a request like
        {"category": 2, "title": "Tetrahydrofuran", "compounds": [77],
         "storage": {"place_id": 6, "amount": 500, "unit": "mL"},
         "fields": {"Manufacturer": "Sigma-Aldrich", "Lot number": "SHBM1234"}}
        :raises InvalidBottle: nothing was created.
        :return: {"id": new bottle id, "problems": [steps that failed after it was created]}
    """
    request = check_request(rm, data)
    has_compounds = bool(request["compounds"])

    item_id = rm.create_item_from_template(request["category"])
    problems = []

    try:
        rm.change_item(item_id, {
            "title": request["title"],
            "metadata": bottle_metadata(request["metadata"], request["fields"], has_compounds),
        })
    except Exception as e:
        problems.append(f"Saving the name and details failed: {e}")

    for compound_id in request["compounds"]:
        try:
            rm.link_compound(item_id, compound_id)
        except Exception as e:
            problems.append(f"Linking compound #{compound_id} failed: {e}")

    try:
        rm.add_to_storage(item_id, request["place_id"], request["amount"], request["unit"])
    except Exception as e:
        problems.append(f"Putting it in its storage place failed: {e}")

    if request["smiles"]:
        try:
            rm.upload_file(item_id, generate_image(request["smiles"]))
        except Exception as e:
            problems.append(f"Adding the structure image failed: {e}")

    return {"id": item_id, "problems": problems}
