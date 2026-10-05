"""
Tags a new bottle with the hazards and peroxide class of its compound(s), so they
show on the bottle and can be searched ("every bottle tagged Peroxide former: B").

  - Hazard tags come from the compound's GHS flags (is_flammable...).
  - The peroxide tag comes from the EPA CompTox peroxide-former lists A-D kept in
    automations/peroxides (the files the peroxide reminder uses), matched by the
    compound's CAS number or InChIKey.

Tags are added when the bottle is created; bottles made earlier are not updated.
"""

import csv
import functools
import re
from pathlib import Path
from typing import Any

PEROXIDE_DIR = Path(__file__).resolve().parent.parent / "automations" / "peroxides"

# eLabFTW compound flag -> tag on the bottle
HAZARD_TAGS = {
    "is_explosive": "Explosive",
    "is_flammable": "Flammable",
    "is_oxidising": "Oxidiser",
    "is_gas_under_pressure": "Gas under pressure",
    "is_corrosive": "Corrosive",
    "is_toxic": "Toxic",
    "is_hazardous2health": "Health hazard",
    "is_serious_health_hazard": "Serious health hazard",
    "is_hazardous2env": "Environmental hazard",
}


@functools.cache
def peroxide_classes() -> dict[str, str]:
    """CAS number and InChIKey -> peroxide-former class (A-D), read once from the EPA lists."""
    classes: dict[str, str] = {}
    for path in sorted(PEROXIDE_DIR.glob("Chemical List PEROXIDES*.csv")):
        match = re.search(r"PEROXIDES([A-D])-", path.name)
        if not match:
            continue
        # utf-8-sig: the EPA exports start with a byte-order mark
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                for key in (row.get("CASRN"), row.get("INCHIKEY")):
                    if key and key.strip():
                        # lists are read A to D, so a chemical on two lists keeps the stricter class
                        classes.setdefault(key.strip(), match.group(1))
    return classes


def peroxide_class(compound: dict[str, Any]) -> str | None:
    """The compound's peroxide-former class, or None if it is on no list."""
    classes = peroxide_classes()
    for key in (compound.get("cas_number"), compound.get("inchi_key")):
        if key and key in classes:
            return classes[key]
    return None


def tags_for(compounds: list[dict[str, Any]]) -> list[str]:
    """The tags for a bottle holding these compounds, without repeats."""
    tags: list[str] = []
    for compound in compounds:
        for flag, tag in HAZARD_TAGS.items():
            if compound.get(flag) and tag not in tags:
                tags.append(tag)
    for compound in compounds:
        clss = peroxide_class(compound)
        if clss and f"Peroxide former: {clss}" not in tags:
            tags.append(f"Peroxide former: {clss}")
    return tags
