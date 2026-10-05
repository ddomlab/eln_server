"""Bring compounds in from PubChem without damaging existing ones.

eLabFTW's own "import from PubChem" (POST /compounds with action=duplicate) and its
plain create both *upsert*: when a unique field (CAS, InChIKey, PubChem ID...)
matches any existing compound, including a deleted one, eLabFTW overwrites that
compound and restores it if deleted, then returns its id. In the lab's ELN this
replaced compound #80 (Hexitol) with Mannitol and brought back deleted #8.

So: look the compound up in PubChem first (read only, see eln_common.pubchem),
refuse if it would clash with a compound we already have, create it with the CAS
the user gave and its hazard flags, and check that eLabFTW really made a new compound.
"""

from typing import Any

from eln_common.resourcemanage import Resource_Manager

# eLabFTW stores hazards as one yes/no field per GHS pictogram
GHS_FLAGS = {
    "GHS01": "is_explosive",
    "GHS02": "is_flammable",
    "GHS03": "is_oxidising",
    "GHS04": "is_gas_under_pressure",
    "GHS05": "is_corrosive",
    "GHS06": "is_toxic",
    "GHS07": "is_hazardous2health",
    "GHS08": "is_serious_health_hazard",
    "GHS09": "is_hazardous2env",
}

# the PubChem fields eLabFTW accepts when creating a compound (molecular_weight is
# not accepted on create, so it is set right after)
CREATE_FIELDS = ["name", "cas_number", "pubchem_cid", "inchi", "inchi_key", "smiles",
                 "iupac_name", "molecular_formula"]


class CompoundClash(Exception):
    """The compound already exists in the ELN (possibly deleted)."""

    def __init__(self, existing: dict[str, Any], reason: str):
        self.existing = existing
        self.reason = reason
        super().__init__(reason)


def summary(compound: dict[str, Any]) -> dict[str, Any]:
    """The few fields the web page shows for an ELN compound."""
    return {
        "id": compound["id"],
        "name": compound.get("name") or "",
        "cas": compound.get("cas_number") or "",
        "formula": compound.get("molecular_formula") or "",
        "deleted": compound.get("state") not in (None, 1),
    }


def find_existing(pubchem: dict[str, Any], cas: str | None,
                  compounds: list[dict[str, Any]]) -> tuple[dict[str, Any], str] | None:
    """
    The ELN compound (any state) that a PubChem result would collide with, and why.
    Checks the unique fields that would be sent: PubChem ID, InChIKey, and the CAS
    actually saved (the user's, else PubChem's; see build_compound_body).
    """
    keys = [
        ("pubchem_cid", pubchem.get("pubchem_cid"), "same PubChem ID"),
        ("inchi_key", pubchem.get("inchi_key"), "same structure (InChIKey)"),
        ("cas_number", cas or pubchem.get("cas_number"), "same CAS number"),
    ]
    for field, value, reason in keys:
        if not value:
            continue
        for compound in compounds:
            if compound.get(field) is not None and str(compound.get(field)) == str(value):
                return compound, reason
    return None


def build_compound_body(pubchem: dict[str, Any], cas: str | None) -> dict[str, Any]:
    """
    The fields sent to eLabFTW, from a PubChem result (eln_common.pubchem.fetch).
    The user's CAS wins over PubChem's; each GHS pictogram turns its hazard flag on.
    """
    body = {field: pubchem.get(field) for field in CREATE_FIELDS}
    body["cas_number"] = cas or pubchem.get("cas_number")
    for pictogram in pubchem.get("pictograms") or []:
        if pictogram in GHS_FLAGS:
            body[GHS_FLAGS[pictogram]] = 1
    # leave out empty fields: an empty unique field can also trigger the upsert
    return {k: v for k, v in body.items() if v not in (None, "")}


def create_compound_safely(rm: Resource_Manager, pubchem: dict[str, Any],
                           cas: str | None) -> dict[str, Any]:
    """
    Creates the compound described by a PubChem result, unless it would touch an
    existing one.
        :raises CompoundClash: the ELN already has this compound (maybe deleted).
        :raises RuntimeError: eLabFTW returned an existing compound's id anyway.
        :return: The new compound as eLabFTW stores it.
    """
    compounds = rm.get_all_compounds()
    clash = find_existing(pubchem, cas, compounds)
    if clash:
        raise CompoundClash(*clash)

    known_ids = {c["id"] for c in compounds}
    new_id = rm.create_compound(build_compound_body(pubchem, cas))
    if new_id in known_ids:
        # the check above should make this impossible; never link to an overwritten compound
        raise RuntimeError(
            f"eLabFTW saved this into existing compound #{new_id} instead of creating a new one; "
            "check that compound by hand")
    if pubchem.get("molecular_weight"):
        rm.patch_compound(new_id, {"molecular_weight": pubchem["molecular_weight"]})
    return rm.get_compound(new_id)
