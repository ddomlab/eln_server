import tempfile
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Draw


def generate_image(smiles: str) -> str:
    mol = Chem.MolFromSmiles(smiles)
    # the basename becomes the uploaded file's real_name; existing resources
    # carry their structure image as "RDKitImage.png", so keep the name
    filename = str(Path(tempfile.gettempdir()) / "RDKitImage.png")
    Draw.MolToFile(mol, filename)
    return filename
