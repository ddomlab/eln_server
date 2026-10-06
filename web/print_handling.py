from automations.labels.generate_label import LabelGenerator
from eln_common.resourcemanage import Resource_Manager


def labels_pdf(rm: Resource_Manager, ids: list[int]) -> bytes:
    """The labels for the given items as one PDF, generated on the fly from their
    current data (rather than fetching the label.pdf stored on each resource)."""
    labelgen = LabelGenerator(rm)
    for id in ids:
        labelgen.add_item(id)
    return labelgen.pdf()
