import pubchempy as pcp
import json
from rdkit import Chem
from eln_common.resourcemanage import Resource_Manager

# CAS numbers fall in the 'name' category on pubchem, so they are searched as names
# you could also search by the common name or any other synonym, however CAS numbers
# should return more consistent results
def get_compound(CAS) -> pcp.Compound:
    compound_list: list[pcp.Compound] = pcp.get_compounds(CAS, "name")
    if len(compound_list) > 1:
        raise ValueError(
            "Multiple compounds with this name have been found, please input a more specific name or CAS number"
        )
    elif len(compound_list) == 0:
        raise ValueError("No compound with this CAS/name has been found")
    compound: pcp.Compound = compound_list[0]
    return compound

def check_if_cas(input: str) -> bool:
    parts = input.split('-')
    if len(parts) != 3:
        return False
    if not (parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit()):
        return False
    if len(parts[0]) < 2 or len(parts[0]) > 7:
        return False
    if len(parts[1]) != 2:
        return False
    if len(parts[2]) != 1:
        return False
    return True

def find_cas(input:list) -> str:
    for item in input:
        if check_if_cas(item):
            return item
    return ""

def canonicalize_smiles(smiles: str) -> str:
    # converts the input SMILES string into a Mol object to be interpreted by RDKit
    # then returns the canonicalized SMILES
    if smiles is None or smiles == "": # stupid workaround for NoneType error, thanks PubChem :(
        return "PubChem Error, could not fetch SMILES"
    mol = Chem.MolFromSmiles(smiles)
    return Chem.MolToSmiles(mol)
    
def pull_values(searchquery: str) -> dict:
    compound: pcp.Compound = get_compound(searchquery)
    values:dict = {
        "Title_0": compound.synonyms[0],
        "Full name": compound.iupac_name,
        "SMILES": canonicalize_smiles(compound.isomeric_smiles),
        "Molecular Weight": compound.molecular_weight,
        "Pubchem Link": f"https://pubchem.ncbi.nlm.nih.gov/compound/{compound.cid}",
        "Hazards Link": f"https://pubchem.ncbi.nlm.nih.gov/compound/{compound.cid}#section=Hazards-Identification",
    }
    if not check_if_cas(searchquery):
        values.update({"CAS": find_cas(compound.synonyms)})
    return values

def fill_in(rm: Resource_Manager, id: int):
    body = rm.get_item(id)
    body = get_filled_dictionary(body)
    rm.change_item(id, body)

def get_filled_dictionary(body: dict) -> dict:
    metadata: dict = json.loads(body["metadata"])
    new_title: str = body["title"]
    if check_if_cas(body["title"]): 
        # if the title is a CAS number, search by CAS number, and replace the title with the first synonym on PubChem
        CAS: str = body["title"]
        values: dict = pull_values(body["title"])
        new_title = values["Title_0"]
    elif "CAS" in metadata["extra_fields"] and metadata["extra_fields"]["CAS"]["value"] != "":
        # if the title is not a CAS but there is a CAS in the metadata, search by that CAS
        CAS = metadata["extra_fields"]["CAS"]["value"]
        values: dict = pull_values(CAS)
    else:
        # otherwise try to search by the non-CAS title
        values: dict = pull_values(body["title"])
        CAS = ""
    metadata["extra_fields"]["Full name"]["value"] = values["Full name"]

    if "SMILES" not in metadata["extra_fields"]:
        # if there isn't a SMILES field, create one
        metadata["extra_fields"]["SMILES"] = {
            "type": "text",
            "value": "",
            "description": "From PubChem",
        }
    metadata["extra_fields"]["SMILES"]["value"] = values["SMILES"]
    if "CAS" not in metadata["extra_fields"]:
        # if there isn't a CAS field, create one
        metadata["extra_fields"]["CAS"] = {
            "type": "text",
            "value": "",
            "description": "",
        }
    metadata["extra_fields"]["CAS"]["value"] = CAS
    if "Molecular Weight" not in metadata["extra_fields"]:
        # if there isn't a molecular weight field, create one #TODO: make this a number
        metadata["extra_fields"]["Molecular Weight"] = {
            "type": "text",
            "value": "",
            "description": "From PubChem (g/mol)",
        }
    metadata["extra_fields"]["Molecular Weight"]["value"] = values["Molecular Weight"]
    if "Pubchem Link" not in metadata["extra_fields"]:
        # if there isn't a Pubchem link field, create one
        metadata["extra_fields"]["Pubchem Link"] = {
            "type": "url",
            "value": "",
            "description": "Link to PubChem page",
        }
    metadata["extra_fields"]["Pubchem Link"]["value"] = values["Pubchem Link"]
    if "Hazards Link" not in metadata["extra_fields"]:
        # if there isn't a hazards link field, create one
        metadata["extra_fields"]["Hazards Link"] = {
            "type": "url",
            "value": "",
            "description": "Link to Hazards section of PubChem",
        }
    metadata["extra_fields"]["Hazards Link"]["value"] = values["Hazards Link"]
    new_body = {
        "title": new_title,
        "category": body["category"],
        "metadata": json.dumps(metadata),
        "rating": 0, # before i figured out tags I used this to mark autofilled items, no longer necessary. this will remove ratings
    }
    return new_body