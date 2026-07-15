from pathlib import Path

import pandas as pd
from tabulate import tabulate

import automations.slackbot as slackbot
from eln_common.resourcemanage import Resource_Manager

current_dir = Path(__file__).parent
classes = ['A', 'B', 'C', 'D']


def send_message(peroxide_class: str, peroxide_list):
    slackbot.send_message(
        f"Please check the following class {peroxide_class} peroxide formers. {len(peroxide_list)} items found:\n"
        + "\n```\n" + tabulate(peroxide_list, headers='keys', tablefmt='grid', showindex=False) + "\n```\n" +
        "See https://ors.od.nih.gov/sr/dohs/Documents/managing-peroxide-formers-in-the-lab.pdf for information about checking peroxide formers.",
        channel=slackbot.PEROXIDE_CHANNEL)


def check_peroxide_formers(items: pd.DataFrame, clss: str):
    assert clss in classes, f"Invalid class {clss}. Valid classes are {classes}"
    df = pd.read_csv(current_dir / f"Chemical List PEROXIDES{clss}-2025-04-21.csv")
    matches = items[items['CAS'].isin(df['CASRN'])]
    if len(matches) > 0:
        send_message(clss, matches[['id', 'title', 'Room', 'Location']].sort_values(by="Location").sort_values(by='Room'))
    return matches


def check_all_classes(rm: Resource_Manager):
    items = rm.get_items_df(size=1000)
    results = {}
    for clss in classes:
        results[clss] = check_peroxide_formers(items, clss)
    return results
