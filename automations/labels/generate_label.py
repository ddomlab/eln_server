from blabel import LabelWriter
import eln_common.config as config
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
        # a falsy date hides the date block in label.html (jinja `if received_date`)
        date = None
        if item["category"] in config.setting("label_date_categories", [2, 3, 4]):
            # items without a Received field just get a blank date on the label
            extra_fields = json.loads(item["metadata"] or "{}").get("extra_fields") or {}
            date = extra_fields.get("Received", {}).get("value", "")
        ## adds records to list to be printed
        if len(item["title"]) > 25:
            item["title"] = item["title"][:22] + '...'
        self.records.append(
            dict(
                id_num=id,
                name=item["title"],
                received_date=date,
                qr_text=config.item_web_url(id),
            )
        )

    # generates pdf for all labels in records
    def write_labels(self, target: str | None = None):
        self.label_writer.write_labels(self.records, target=target or self.path)
        self.records = []
