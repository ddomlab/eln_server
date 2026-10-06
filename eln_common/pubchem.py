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

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
PROPERTIES = "Title,IUPACName,MolecularFormula,MolecularWeight,SMILES,InChI,InChIKey"
TIMEOUT = 30


def check_if_cas(text: str) -> bool:
    """Whether the text is shaped like a CAS number: 2-7 digits, 2 digits, 1 digit (e.g. 109-99-9)."""
    return re.fullmatch(r"\d{2,7}-\d{2}-\d", text) is not None


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


OFFICIAL_SOURCE = "Regulation (EC) No 1272/2008"  # the EU's legal (harmonised) classification
ECHA_SOURCE = "European Chemicals Agency (ECHA)"   # company notifications, summarised by ECHA


def ghs_pictograms(cid: int) -> list[str] | None:
    """
    The GHS hazard pictograms for a compound, e.g. ["GHS02", "GHS07"], chosen the way a
    supplier's SDS would be (PubChem lists one classification per source, and some are
    for other grades or even other substances):
      1. the EU's official classification, when there is one;
      2. otherwise ECHA's main summary (the one with the most company reports); none if
         most of those reports say the compound is not hazardous;
      3. otherwise every other source's pictograms together.
        :return: The sorted pictogram codes; [] when PubChem classifies the compound
            with no pictograms; None when PubChem has no GHS classification at all
            (hazards unknown: check the supplier's SDS).
    """
    data = _json(requests.get(f"{PUG_VIEW}/data/compound/{cid}/JSON",
                              params={"heading": "GHS Classification"}, timeout=TIMEOUT))
    if data is None:
        return None
    sources = _ghs_sources(data["Record"])

    official = [s for s in sources.values() if s["source"].startswith(OFFICIAL_SOURCE)]
    if official:
        return sorted(set().union(*(s["pictograms"] for s in official)))

    echa = [s for s in sources.values() if s["source"] == ECHA_SOURCE and s["reports"]]
    if echa:
        main = max(echa, key=lambda s: s["reports"])
        if main["not_hazardous_percent"] >= 50:
            return []
        if main["pictograms"]:
            return sorted(main["pictograms"])

    return sorted(set().union(set(), *(s["pictograms"] for s in sources.values())))


def _ghs_sources(record: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """
    PubChem's GHS classification, one entry per source (reference number):
    {source name, pictograms, reports (ECHA's company report count, else 0),
    not_hazardous_percent (from ECHA's "does not meet GHS hazard criteria for X%")}.
    """
    names = {r["ReferenceNumber"]: r.get("SourceName", "") for r in record.get("Reference", [])}
    sources: dict[int, dict[str, Any]] = {}
    for info in _information(record):
        ref = info.get("ReferenceNumber")
        source = sources.setdefault(ref, {"source": names.get(ref, ""), "pictograms": set(),
                                          "reports": 0, "not_hazardous_percent": 0.0})
        texts = info.get("Value", {}).get("StringWithMarkup", [])
        if info.get("Name") == "Pictogram(s)":
            for text in texts:
                for markup in text.get("Markup", []):
                    # the icon's URL names the pictogram: .../images/ghs/GHS02.svg
                    match = re.search(r"(GHS\d\d)\.svg$", markup.get("URL", ""))
                    if match:
                        source["pictograms"].add(match.group(1))
        elif info.get("Name") == "ECHA C&L Notifications Summary" and texts:
            match = re.search(r"per (\d+) reports", texts[0].get("String", ""))
            if match:
                source["reports"] = int(match.group(1))
        elif info.get("Name") == "Note" and texts:
            match = re.search(r"does not meet GHS hazard criteria for ([\d.]+)%", texts[0].get("String", ""))
            if match:
                source["not_hazardous_percent"] = float(match.group(1))
    return sources


def _information(section: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every Information entry in a PubChem record, at any depth of its sections."""
    yield from section.get("Information", [])
    for child in section.get("Section", []):
        yield from _information(child)
