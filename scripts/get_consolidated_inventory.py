"""One-off script: group inventory by CAS/quantity into a consolidated CSV. Uses the local api_key file."""
from eln_common.resourcemanage import Resource_Manager

rm = Resource_Manager()

if __name__ == "__main__":
    df = rm.get_items_df(size=1000)

    # Clean and normalize necessary columns
    df['CAS'] = df['CAS'].astype(str).str.strip().str.lower()
    df['title'] = df['title'].astype(str).str.strip().str.lower()
    df['Quantity Units'] = df['Quantity Units'].astype(str).str.strip().str.lower()

    # Filter out invalid or incomplete rows
    df_valid = df[df['Quantity'].notnull() & df['CAS'].notnull() & df['Quantity Units'].notnull()]

    # Group by CAS, title, quantity per container, and units
    grouped = (
        df_valid
        .groupby(['title', 'CAS', 'Quantity', 'Quantity Units'])
        .size()
        .reset_index(name='Number of Containers')
    )

    grouped = grouped[['title', 'CAS', 'Number of Containers', 'Quantity', 'Quantity Units']]
    grouped.to_csv("consolidated_inventory.csv", index=False)
    print("Saved to consolidated_inventory.csv")
