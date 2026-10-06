from blabel import LabelWriter
from pathlib import Path

static_dir = Path(__file__).parent.parent / "static"


def label_pdf(caption: str = "", codecontent: str | None = None, longcaption: str | None = None, icon: str | None = None, height=18) -> bytes:
    """A single flex label as PDF data (made in memory, so two people printing at once
    can't get each other's labels)
    :param caption: The caption for the label
    :param codecontent: The content for the QR code, if None, no QR code is generated
    :param longcaption: A longer caption for the label, if None, no long caption is displayed
    :param icon: An icon to be displayed on the label, if None, no icon is displayed
    :param height: The height of the label in mm, default is 18mm
    """
    label_writer = LabelWriter(
        str(static_dir / "Flex_Label.html"),
        default_stylesheets=(str(static_dir / "flex_style.css"),),
    )

    if codecontent is not None and icon is not None:
        raise ValueError("Cannot have both codecontent and icon at the same time")
    records = [
        dict(
            caption=caption,
            qr_text=codecontent,
            longcaption=longcaption,
            icon=icon,
            user_height=height,
        )
    ]
    return label_writer.write_labels(records, target=None)
