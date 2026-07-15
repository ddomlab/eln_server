"""One-off script: create eLab compounds for every valid CAS in the inventory. Uses the local api_key file."""
from eln_common.fill_info import check_if_cas
from eln_common.resourcemanage import Resource_Manager

rm = Resource_Manager()

if __name__ == "__main__":
    df = rm.get_items_df(size=1000)
    for d in df["CAS"]:
        if check_if_cas(str(d)):
            print(d)
            rm.find_and_create_compound(CAS=str(d))
