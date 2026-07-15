"""One-off script: link items to eLab compounds by matching CAS numbers. Uses the local api_key file."""
from eln_common.fill_info import check_if_cas
from eln_common.resourcemanage import Resource_Manager

rm = Resource_Manager()

if __name__ == "__main__":
    items = rm.get_items_df(size=1000)[["id", "CAS"]]
    comps = rm.get_compounds_df()[["id", "cas_number"]]

    for _, item_row in items.iterrows():
        cas = str(item_row["CAS"]).strip()
        resource_id = item_row["id"]

        if check_if_cas(cas):
            # Find matching compound row(s) by CAS
            matching_comps = comps[comps["cas_number"].astype(str).str.strip() == cas]
            print(f"Found {len(matching_comps)} matching compounds for CAS: {cas} and resource ID: {resource_id}")
            for _, comp_row in matching_comps.iterrows():
                rm.associate_compound(comp_row["id"], resource_id)
