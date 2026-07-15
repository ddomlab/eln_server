import json

import automations.image_generator as ig
import automations.slackbot as slackbot
from automations.labels.generate_label import LabelGenerator
import eln_common.config as config
import eln_common.fill_info as fill_info
from eln_common.resourcemanage import Resource_Manager


def create_and_upload_labels(rm: Resource_Manager, id: int):
    for file in rm.get_uploaded_files(id):
        if file.to_dict()["real_name"] == "label.pdf":
            print(f"Label already exists for {id}")
            return
            # rm.delete_upload(id, file.to_dict()["id"])
    labelgen = LabelGenerator(rm)
    labelgen.add_item(id)
    labelgen.write_labels()
    rm.upload_file(id, str(labelgen.path))


def check_and_fill_image(rm: Resource_Manager, smiles: str, id: int):
    ## upload RDKit image if it isn't there
    files = rm.get_uploaded_files(id)
    for file in files:
        if file.to_dict()["real_name"] == "RDKitImage.png":
            print("Image already exists")
            rm.delete_upload(
                id, file.to_dict()["id"]
            )  # delete the old image, turn off usually
            # return # if the image already exists, don't upload it again
    if smiles != "":
        imagepath = ig.generate_image(smiles)
        print(imagepath)
        rm.upload_file(id, imagepath)


def process_item(rm: Resource_Manager, item: dict, force=False, info=True, label=True, image=True):
    """Runs the autofill steps (label upload, info fill, RDKit image) on a single item dict."""
    if item['category'] is None:  # skip items that don't have a category
        return
    type: int = int(item["category"])
    id = item["id"]
    # Legacy: /print now generates labels on the fly, so the label.pdf upload is
    # only made when ELN_AUTO_UPLOAD_LABELS is set (see eln_common/config.py).
    if label and config.AUTO_UPLOAD_LABELS:
        create_and_upload_labels(rm, id)
    if type in config.setting("chemical_categories", [2, 3]):  # only chemical-like categories get info/images
        metadata = json.loads(item["metadata"])
        # check if the item has been autofilled already, or if force is true
        if (item["tags"] is None or "Autofilled" not in item["tags"] or force) and not rm.is_item_busy(id):
            if info:
                try:
                    fill_info.fill_in(rm, id)
                    rm.add_tag(id, "Autofilled")
                except ValueError as e:
                    if "Null molecule" in str(e):
                        slackbot.send_message(f"Invalid SMILES provided in SMILES field for item {id}. See {config.item_web_url(id)}")
                    if item["tags"] is None or "Not In PubChem" not in item["tags"]:
                        rm.add_tag(id, "Not In PubChem")
                        print(str(e))
                        if "No compound" in str(e):
                            print(f"No compound found for item {id}")
                            slackbot.send_message(f"No compound found in PubChem for item {id}. See {config.item_web_url(id)}")
                        elif "Multiple compounds" in str(e):
                            print(f"Multiple compounds found for item {id}")
                            slackbot.send_message(f"Multiple compounds found in PubChem for item {id}. Manual addition of chemical properties required. See {config.item_web_url(id)}")
            if image:
                try:
                    smiles: str = metadata["extra_fields"]["SMILES"]["value"]
                    check_and_fill_image(rm, smiles, id)
                except KeyError:
                    print(f"No SMILES found for item {id}")
                except ValueError:
                    if item["tags"] is None or "Invalid SMILES" not in item["tags"]:
                        rm.add_tag(id, "Invalid SMILES")
                        slackbot.send_message(f"Invalid SMILES found for item {id}, cannot generate image.")
        else:
            print(f"Item {id} has already been filled in")


def autofill_item(rm: Resource_Manager, id: int, force=False, info=True, label=True, image=True):
    """Fetches a single item by id and runs the autofill steps on it."""
    process_item(rm, rm.get_item(id), force=force, info=info, label=label, image=image)


def autofill(rm: Resource_Manager, start=300, end=None, force=False, info=True, label=True, image=True, size=5):
    """
    This method controls which functions are called and handles deciding which items to autofill.
    The start and end parameters can be used to edit a certain range of items.
    This is not necessary in typical use, when the method is run automatically on
    the 5 most recently created items, and only if their ID is greater than 300,
    but the functionality is there if needed--for example:
    manually running autofill on a range of items that were created
    before the autofill was implemented.

        :param Resource_Manager rm: the Resource_Manager (and thus the API key) to act as
        :param int start: lowest bound of item id to autofill
        :param int end: highest bound of item id to autofill, no end by default
        :param bool force: whether to fill in items that have already been filled in--False by default
        :param bool info: whether to fill in the information fields--True by default
        :param bool label: whether to generate a label pdf--True by default
        :param bool image: whether to generate an RDKit image--True by default
        :param int size: number of recent entries to check. Default is 5 to prevent unnecessary traffic. Set to higher to check old entries.

    ## NOTE:
    if you want to edit a range of old Resources, and you set `start` to a very low number,
    you will likely have to set `size` to a higher number in order to pull enough entires to reach the start number
    """
    items: list[dict] = rm.get_items(size=size)
    for item in items:
        id = item["id"]
        if (end is None and id >= start) or (end is not None and id in range(start, end)):
            process_item(rm, item, force=force, info=info, label=label, image=image)
