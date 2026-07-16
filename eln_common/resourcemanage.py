# right now i intend to create a class with a few methods to control
# resources (add/delete/edit) here, if this gets too complicated i may decide to
# split it into seperate files

# this contains mostly code written by Connor found in Python_Scripts.zip in the Onedrive.
# i am mostly writing wrappers and making the code a little more abstract and generally usable
import eln_common.config as config
from typing import Any
import json
import requests
import pandas as pd

class Resource_Manager:
    def __init__(self, key: str | None = None):
        self.itemsapi = config.load_items_api(key)
        self.expapi = config.load_experiments_api(key)
        # self.add_commentsapi = config.load_comments_api(key)
        self.uploadsapi = config.load_uploads_api(key)
        self.printer_path = config.PRINTER_PATH  # this is the path where the labels will be saved, it is set in the config file, and accessed in printer/generate_label.py
        header = config.get_api_key(key).default_headers
        self.header = {**header, **{"Content-type": "application/json"}}


    def post_url(self,url:str,json:dict|None=None) -> requests.Response:
        """
        TODO: is this necessary? Either use this method everywhere or not at all
        Posts a URL to the ELN with the given URL. Used for more manual processes.
            :param str url: The URL to be posted.
        """
        url = config.URL + url
        return requests.post(url, headers=self.header, json=json)
    def get_url(self,url:str) -> requests.Response:
        """
        TODO: is this necessary? Either use this method everywhere or not at all
        Sends a GET request to the ELN with the given URL. Used for more manual processes.
            :param str url: The URL to be posted.
        """
        url = config.URL + url
        return requests.get(url, headers=self.header)
    def create_item(self, category: int, body_dict: dict[str, Any]) -> int:
        """
        Creates an item in the ELN with the given category and body_dict.
            :param int category: The resource category ID of the item to be created.
                Category IDs are team-specific; list them with get_items_types().
            :param dict body_dict: The body of the item to be created.
            :return: The ID of the newly created item.
        """
        response = self.itemsapi.post_item_with_http_info( # type: ignore
            body={
                "category_id": category,
            }
        )
        locationHeaderInResponse: str = str(response[2].get("Location")) #type: ignore
        print(f"The newly created item is here: {locationHeaderInResponse}")
        item_id:int = int(locationHeaderInResponse.split("/").pop())
        self.change_item(item_id, body_dict)
        return item_id

    def change_item(self, id: int, body_dict: dict[str, Any]) -> None:
        """
        Changes the item with the given ID to the given body_dict.
            :param int id: The ID of the item to be changed.
            :param dict body_dict: The body of the item to be changed.
        """
        # elabapi_python >= 5 moved `body` to the first positional parameter
        self.itemsapi.patch_item(body_dict, id) #type: ignore
    
    # def add_comment(self, id: int, comment: str) ->None:
    #     """
    #     Adds a comment to an item in the ELN with the given ID and comment.
    #         :param int id: The ID of the item to be commented on.
    #         :param str comment: The comment to be added to the item.
    #     """
    #     self.commentsapi.

    def upload_file(
        self, id:int, path:str, comment:str="", resource_type:str="items"
    ):  
        """
        Uploads a file to the ELN with the given ID and path.
            :param int id: The ID of the item to be uploaded to.
            :param str path: The path of the file to be uploaded.
            :param str comment: The comment to be added to the file.
            :param str resource_type: The type of resource to be uploaded to. Can be 'item' or 'experiment'.
        """
        self.uploadsapi.post_upload(resource_type, id, file=path, comment=comment) #type: ignore
    def experiment_item_link(self, experiment_id: int, item_id: int):
        """
        Links an item to an experiment in the ELN with the given experiment ID and item ID.
            :param int experiment_id: The ID of the experiment to be linked to.
            :param int item_id: The ID of the item to be linked to.
        """
        url = (
            "/experiments/"
            + str(experiment_id)
            + "/items_links/"
            + str(item_id)
        )
        # checks if the resource and experiment exist, throws error if not
        try:
            self.get_item(item_id)
            self.get_experiment(experiment_id)
        except (config.elabapi_python.rest.ApiException, requests.HTTPError):
            raise ValueError("Experiment or item does not exist")
        self.post_url(url)
    def find_and_create_compound(self, CAS:str):
        """
        Finds a compound in the ELN with the given CAS number and creates it if it does not exist.
            :param str CAS: The CAS number of the compound to be found.
            :return: The ID of the compound.
        """
        self.post_url("/compounds/", json={"action":"duplicate", "cas":CAS})
    def associate_compound(self, comp_id:int,res_id:int):
        """
        Associates a compound with the given CAS number to an item in the ELN with the given ID.
            :param str CAS: The CAS number of the compound to be associated.
            :param int id: The ID of the item to be associated with.
        """
        self.post_url("/items/" + str(res_id) + "/compounds/" + str(comp_id))
    
    def get_compounds(self):
        """
        Gets a list of compounds in the ELN as dictionaries.
            :return: A list of dictionaries containing the compounds.
        """
        return self.get_url("/compounds?limit=1000").json()
    def add_tag(self, item_id: int, tag: str):
        """
        Adds a tag to an item in the ELN with the given item ID and tag. Take care to use correct capitalization/whitespace
            :param int item_id: The ID of the item to be tagged.
            :param str tag: The tag to be added to the item."""
        url = config.URL + "/items/" + str(item_id) + "/tags/"
        requests.post(url, headers=self.header, json={"tag": tag})

    def delete_upload(
        self, id:int, upload_id:int, resource_type:str="items"
    ):  
        """Deletes an upload from the ELN with the given ID and upload ID.
            :param int id: The ID of the item to be deleted.
            :param int upload_id: The ID of the upload to be deleted.
            :param str resource_type: The type of resource to be deleted. Can be 'item' or 'experiment'."""
        self.uploadsapi.delete_upload(resource_type, id, upload_id) #type: ignore   
    def get_metadata(self, id:int) -> dict[str, Any]:
        """
        Gets ONLY the metadata of an item in the ELN with the given ID.
            :param int id: The ID of the item to be gotten.
            :return: A dictionary containing the "metadata" of the item.
            """
        return json.loads(self.get_item(id)["metadata"])
    
    def get_item(self, id:int) -> dict[str, Any]:
        """
        Gets an item in the ELN with the given ID as a dictionary.
            :param int id: The ID of the item to be gotten.
            :return: A dictionary containing the item information, with {title, id, category, metadata,rating,tags} and many more fields."""
        # Fetched as raw API JSON rather than through the generated Item model:
        # the server sends "metadata" as a JSON string, which elabapi_python >= 5
        # deserializes into a Metadata model and silently nulls out. All callers
        # rely on metadata staying a json.loads-able string.
        response = self.get_url("/items/" + str(id))
        response.raise_for_status()
        return response.json()
        # this dictionary should contain:
        # title, id, category, metadata, rating
        # a lot of items are contained in the metadata field, which is a json string
        # this can be easily converted to/from a python dictionary in any method used to edit metadata
    def get_experiment(self, id:int) -> dict[str, Any]:
        """
        Gets an experiment in the ELN with the given ID as a dictionary.
            :param int id: The ID of the experiment to be gotten.
            :return: A dictionary containing the experiment information, with {title, id, category, metadata,rating,tags} and many more fields.
        """
        # raw JSON for the same reason as get_item: keep "metadata" a string
        response = self.get_url("/experiments/" + str(id))
        response.raise_for_status()
        return response.json()

    def get_items_types(self) -> list[dict[str,Any]]: 
        """
        Gets the item type templates as dictionaries from the ELN.
            :return: A list of dictionaries containing the item type templates.
        """
        # construct full API URL
        url = (
            config.URL
            + "/items_types"
        )
        return requests.get(url, headers=self.header).json()

    def get_items_type(self, id: int) -> dict[str, Any]:
        """
        Gets a single item type template as a dictionary. Unlike the
        get_items_types() listing, this includes the "metadata" field
        (eLabFTW >= 5.6 omits it from list responses).
            :param int id: The ID of the item type to be gotten.
            :return: A dictionary containing the item type template.
        """
        response = self.get_url("/items_types/" + str(id))
        response.raise_for_status()
        return response.json()

    def get_items_statuses(self) -> list[dict[str, Any]]:
        """
        Gets the team's resource status list from the ELN.
            :return: A list of dictionaries with {id, title, color, ...} per status.
        """
        return self.get_url("/teams/current/items_status").json()

    def get_items(self, size:int=15, with_metadata:bool=False) -> list[dict[str, Any]]:
        """
        Gets a list of items in the ELN as dictionaries.
            :param int size: The number of items to be gotten. Defaults to 15, setting it too high (~1000) causes it to default back to 15.
            :param bool with_metadata: Whether to include the "metadata" field on each item, at the cost of a slower query.
            :return: A list of dictionaries containing the items.
        """
        # returns the most recent 15 if a size is not specified
        #TODO: figure out the max number of items that can be returned
        # construct full API URL
        url = (
            config.URL
            + "/items?limit="
            + str(size)
        )
        if with_metadata:
            # eLabFTW >= 5.6 omits "metadata" from plain list responses, but
            # extended-search results still carry it, so use a query that
            # matches every item
            url += "&extended=" + requests.utils.quote("date:>1970-01-01")
        return requests.get(url, headers=self.header).json()
    def get_experiments(self) -> list[object]:
        """
        Gets a list of experiments in the ELN as dictionaries.
            :return: A list of dictionaries containing the experiments.
        """
        return self.expapi.read_experiments() #type: ignore

    def search_experiments(self, query: str = "") -> list[dict[str, Any]]:
        """
        Searches experiments in the ELN by title/body text.
            :param str query: The search string; empty returns the most recent experiments.
            :return: A list of dictionaries containing the matching experiments.
        """
        response = self.get_url("/experiments?q=" + requests.utils.quote(query))
        response.raise_for_status()
        return response.json()

    def get_uploaded_files(self, id:int, resource_type:str="items") -> list:
        """
        Gets a list of uploaded files in the ELN with the given ID.
            :param int id: The ID of the item to be gotten.
            :param str resource_type: The type of resource to be gotten. Can be 'item' or 'experiment'.
            :return: A list of file objects that can be written to a file.
        """
        return self.uploadsapi.read_uploads( #type: ignore
            resource_type, id
        )
    def is_item_busy(self, id:int) -> bool:
        """
        Checks if an item in the ELN with the given ID is being edited.
            :param int id: The ID of the item to be checked.
            :return: True if the item is busy, False otherwise.
        """
        return self.get_url('/items/' + str(id)).json()['exclusive_edit_mode'] != [] # return True if item is busy, False otherwise
    def json_loads(self, x): 
        """function to get dictionaries from json, accounting for elements that may be dictionaries already, json strings, or None """
        if isinstance(x, dict):
            return x
        if isinstance(x, str):
            try:
                return json.loads(x)
            except json.JSONDecodeError:
                return {}
        return {}
    def get_items_df(self, size:int=15):
        """
        Gets a list of items in the ELN as a pandas DataFrame.
            :param int size: The number of items to be gotten. Defaults to 15. Max of 9999.
            :return: A pandas DataFrame containing the items.
        """
        assert size <= 9999, "Size must be less than or equal to 9999"
        assert size > 0, "Size must be greater than 0"

        # TODO: consider moving get_items_df() to a different file so pandas isn't a req for simpler stuff
       

        def flatten_extra_fields(extra):
            if not isinstance(extra, dict):
                return {}

            flat = {}
            for k, v in extra.items():
                if not isinstance(v, dict):
                    continue

                # Extract the main value
                flat[k] = v.get("value")

                # Handle units if present
                if "unit" in v:
                    if v["unit"] == "":
                        v["unit"] = v["units"][0]
                    flat[f"{k} Units"] = v["unit"]
                
            return flat
        
        df: pd.DataFrame = pd.DataFrame(self.get_items(size, with_metadata=True))
        df['metadata'] = df['metadata'].apply(self.json_loads)
        metadata: pd.DataFrame = df['metadata'].apply(pd.Series)
        extra_fields_df: pd.DataFrame = metadata['extra_fields'].apply(flatten_extra_fields).apply(pd.Series)
        df = pd.concat([df.drop(columns='metadata'), metadata.drop(columns='extra_fields'), extra_fields_df], axis=1)
        return df
    def get_compounds_df(self) -> pd.DataFrame:
        """
        Gets a list of compounds in the ELN as a pandas DataFrame.
            :return: A pandas DataFrame containing the compounds.
        """
        df: pd.DataFrame = pd.DataFrame(self.get_compounds())
        return df
    def get_resources_categories(self) -> list[dict[str, Any]]:
        """
        Gets the resource categories from the ELN.
            :return: A list of dictionaries containing the resource categories.
        """
        url = config.URL + "/teams/current/resources_categories"
        return requests.get(url, headers=self.header).json()