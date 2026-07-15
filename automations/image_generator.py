import tempfile
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Draw


def generate_image(smiles: str) -> str:
    mol = Chem.MolFromSmiles(smiles)
    # the basename becomes the uploaded file's real_name, which autofill checks
    # for, so it must stay "RDKitImage.png"
    filename = str(Path(tempfile.gettempdir()) / "RDKitImage.png")
    Draw.MolToFile(mol, filename)
    return filename
