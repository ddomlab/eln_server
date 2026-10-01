"""Bring compounds in from PubChem without damaging existing ones.

eLabFTW's own "import from PubChem" (POST /compounds with action=duplicate) and its
plain create both *upsert*: when a unique field (CAS, InChIKey, PubChem ID...)
matches any existing compound, including a deleted one, eLabFTW overwrites that
compound and restores it if deleted, then returns its id. In the lab's ELN this
replaced compound #80 (Hexitol) with Mannitol and brought back deleted #8.

So: look the compound up in PubChem first (read only), refuse if it would clash
with a compound we already have, create it with the CAS the user gave, and check
that eLabFTW really made a new compound.
"""

from typing import Any

from eln_common.resourcemanage import Resource_Manager


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
        ("pubchem_cid", pubchem.get("cid"), "same PubChem ID"),
        ("inchi_key", pubchem.get("inChIKey"), "same structure (InChIKey)"),
        ("cas_number", cas or pubchem.get("cas"), "same CAS number"),
    ]
    for field, value, reason in keys:
        if not value:
            continue
        for compound in compounds:
            if compound.get(field) is not None and str(compound.get(field)) == str(value):
                return compound, reason
    return None


def build_compound_body(pubchem: dict[str, Any], cas: str | None) -> dict[str, Any]:
    """The fields sent to eLabFTW, from a PubChem result. The user's CAS wins over PubChem's."""
    body = {
        "name": pubchem.get("name"),
        "cas_number": cas or pubchem.get("cas"),
        "pubchem_cid": pubchem.get("cid"),
        "inchi": pubchem.get("inChI"),
        "inchi_key": pubchem.get("inChIKey"),
        "smiles": pubchem.get("smiles"),
        "iupac_name": pubchem.get("iupacName"),
        "molecular_formula": pubchem.get("molecularFormula"),
        "is_corrosive": pubchem.get("isCorrosive"),
        "is_explosive": pubchem.get("isExplosive"),
        "is_flammable": pubchem.get("isFlammable"),
        "is_gas_under_pressure": pubchem.get("isGasUnderPressure"),
        "is_hazardous2env": pubchem.get("isHazardous2env"),
        "is_hazardous2health": pubchem.get("isHazardous2health"),
        "is_serious_health_hazard": pubchem.get("isSeriousHealthHazard"),
        "is_oxidising": pubchem.get("isOxidising"),
        "is_toxic": pubchem.get("isToxic"),
    }
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
    if pubchem.get("molecularWeight"):
        # not accepted on create, so it is set right after
        rm.patch_compound(new_id, {"molecular_weight": pubchem["molecularWeight"]})
    return rm.get_compound(new_id)
