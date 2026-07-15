from pathlib import Path

from automations.labels.generate_label import LabelGenerator
from eln_common.resourcemanage import Resource_Manager

temp_path = str(Path(__file__).parent.parent / "static" / "print.pdf")


def add_item(rm: Resource_Manager, ids: list[int]):
    """Generates the labels for the given items on the fly (rather than fetching
    the label.pdf stored on each resource) and writes them to static/print.pdf."""
    labelgen = LabelGenerator(rm)
    for id in ids:
        labelgen.add_item(id)
    labelgen.write_labels(target=temp_path)
