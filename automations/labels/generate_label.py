from blabel import LabelWriter
from eln_common.resourcemanage import Resource_Manager
import json
from pathlib import Path

current_dir = Path(__file__).parent


class LabelGenerator:
    def __init__(self, rm: Resource_Manager):
        self.label_writer = LabelWriter(
            str(current_dir / "label.html"),
            default_stylesheets=(str(current_dir / "style.css"),),
        )
        self.records = []
        self.rm = rm
        self.path = self.rm.printer_path

    def add_item(self, id: int):
        item: dict = self.rm.get_item(id)
        date = ""
        if item["category"] == 1:
            date = None  # making date = None trips the if statement in the label.html file. this is because jinja can check if a variable exists or not
        elif item["category"] in range(2, 5):
            date = json.loads(item["metadata"])["extra_fields"]["Received"]["value"]
        ## adds records to list to be printed
        if len(item["title"]) > 25:
            item["title"] = item["title"][:22] + '...'
        self.records.append(
            dict(
                id_num=id,
                name=item["title"],
                received_date=date,
                qr_text=f"https://eln.ddomlab.org/database.php?mode=view&id={id}",
            )
        )

    # generates pdf for all labels in records
    def write_labels(self):
        self.label_writer.write_labels(self.records, target=self.path)
        self.records = []
