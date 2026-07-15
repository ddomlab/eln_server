"""One-off script: dump the inventory to a CSV. Uses the local api_key file."""
import csv
from datetime import date

from eln_common.resourcemanage import Resource_Manager

rm = Resource_Manager()

target_columns = [
    # "id",
    "title",
    "CAS",

    "Quantity",
    "Quantity Units",
    "category",
    "Room",
    "Location",

    "State",
    "Opened",
    "Received",

    "Mn",
    "Mw",
    "PDI",
    "SMILES",
    "BigSMILES",
    "Full name",

    "Lot number",
    # "Hazards Link",
    "Manufacturer",
    # "Pubchem Link",
    "Container type",
    "Molecular Weight",
    "Solvent",
    "Solvent CAS",
    "Concentration",
    "Solvent SMILES",
    "Purity",
    "Big SMILES",
    "Name",
    "Smile",
    "Big Smile"
]

if __name__ == "__main__":
    df = rm.get_items_df(size=1000)
    df = df[target_columns]
    outfile = f"{date.today().isoformat()}_inventory.csv"
    df.to_csv(outfile, index=False, quoting=csv.QUOTE_NONNUMERIC)
    print(f"Inventory saved to {outfile}")
