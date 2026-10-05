"""
Reads compound details and GHS hazard pictograms straight from PubChem.

The app used to ask eLabFTW to look compounds up in PubChem, but eLabFTW's lookup
by PubChem ID leaves out the hazard flags, so compounds added through the app had no
hazard pictograms. Everything now comes from PubChem's own REST API, and eLabFTW is
only where the compound is saved (see compound_import).

Results use eLabFTW's compound field names (cas_number, inchi_key...), so they can
be compared with existing compounds and sent to eLabFTW as they are.
"""

import re
from typing import Any, Iterator

import requests

from eln_common.fill_info import check_if_cas

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
PROPERTIES = "Title,IUPACName,MolecularFormula,MolecularWeight,SMILES,InChI,InChIKey"
TIMEOUT = 30


def _json(response: requests.Response) -> dict[str, Any] | None:
    """The answer as JSON, or None when PubChem has no such record (404 NotFound)."""
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _from_properties(props: dict[str, Any]) -> dict[str, Any]:
    """One PubChem property row, renamed to eLabFTW's compound fields."""
    weight = props.get("MolecularWeight")
    return {
        "pubchem_cid": props["CID"],
        "name": props.get("Title"),
        "iupac_name": props.get("IUPACName"),
        "molecular_formula": props.get("MolecularFormula"),
        "molecular_weight": float(weight) if weight else None,
        "smiles": props.get("SMILES"),
        "inchi": props.get("InChI"),
        "inchi_key": props.get("InChIKey"),
    }


def search(cas: str | None = None, name: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """
    Finds compounds in PubChem by CAS number or by name. Saves nothing.
        :return: Up to `limit` matches (see _from_properties) with their cas_number;
            an empty list when PubChem has no match.
    """
    query = cas or name
    if not query:
        raise ValueError("Give a CAS number or a name")
    # sent as form data rather than in the URL, so names with "/" or "#" work
    data = _json(requests.post(f"{PUG}/compound/name/property/{PROPERTIES}/JSON",
                               data={"name": query}, timeout=TIMEOUT))
    if data is None:
        return []
    found = [_from_properties(p) for p in data["PropertyTable"]["Properties"][:limit]]
    for compound in found:
        compound["cas_number"] = cas or cas_number(compound["pubchem_cid"])
    return found


def fetch(cid: int) -> dict[str, Any] | None:
    """
    Everything the app saves about one PubChem compound: details, CAS and hazard pictograms.
        :return: As search(), plus "pictograms" (see ghs_pictograms); None if PubChem has no such CID.
    """
    data = _json(requests.get(f"{PUG}/compound/cid/{cid}/property/{PROPERTIES}/JSON", timeout=TIMEOUT))
    if data is None:
        return None
    compound = _from_properties(data["PropertyTable"]["Properties"][0])
    compound["cas_number"] = cas_number(cid)
    compound["pictograms"] = ghs_pictograms(cid)
    return compound


def cas_number(cid: int) -> str | None:
    """The first CAS number among the compound's PubChem synonyms (PubChem lists the main one first)."""
    data = _json(requests.get(f"{PUG}/compound/cid/{cid}/synonyms/JSON", timeout=TIMEOUT))
    if data is None:
        return None
    synonyms = data["InformationList"]["Information"][0].get("Synonym", [])
    return next((s for s in synonyms if check_if_cas(s)), None)


def ghs_pictograms(cid: int) -> list[str] | None:
    """
    The GHS hazard pictograms PubChem lists for a compound, e.g. ["GHS02", "GHS07"].
    PubChem gives one classification per source (ECHA, suppliers...); a pictogram is
    included if any source gives it, as the more cautious choice.
        :return: The sorted pictogram codes; [] when PubChem classifies the compound
            with no pictograms; None when PubChem has no GHS classification at all
            (hazards unknown: check the supplier's SDS).
    """
    data = _json(requests.get(f"{PUG_VIEW}/data/compound/{cid}/JSON",
                              params={"heading": "GHS Classification"}, timeout=TIMEOUT))
    if data is None:
        return None
    found = set()
    for info in _information(data["Record"]):
        if info.get("Name") != "Pictogram(s)":
            continue
        for text in info.get("Value", {}).get("StringWithMarkup", []):
            for markup in text.get("Markup", []):
                # the icon's URL names the pictogram: .../images/ghs/GHS02.svg
                match = re.search(r"(GHS\d\d)\.svg$", markup.get("URL", ""))
                if match:
                    found.add(match.group(1))
    return sorted(found)


def _information(section: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every Information entry in a PubChem record, at any depth of its sections."""
    yield from section.get("Information", [])
    for child in section.get("Section", []):
        yield from _information(child)
