"""
Routine checks on bottles (e.g. testing peroxide formers), kept as eLabFTW steps.

A bottle with a tag listed in automations/routine_checks.yaml gets a step such as
"Test for peroxides (class B), due 2027-04-06" when it is marked open. "Tested"
ticks it and adds the next one; "Mark Empty" closes it (see bottle_actions). The
due date is written into the step's text as well as its deadline, because eLabFTW
clears the deadline when a step is ticked.
"""

import calendar
import functools
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from eln_common.resourcemanage import Resource_Manager

RULES_PATH = Path(__file__).resolve().parent.parent / "automations" / "routine_checks.yaml"


@functools.cache
def rules() -> list[dict[str, Any]]:
    """The checks from the rules file: [{tag, step, every_months}]."""
    with RULES_PATH.open() as f:
        checks = (yaml.safe_load(f) or {}).get("checks") or []
    for check in checks:
        if not check.get("tag") or not check.get("step") or not isinstance(check.get("every_months"), int) \
                or check["every_months"] < 1:
            raise ValueError(f"{RULES_PATH}: each check needs a tag, a step and every_months >= 1: {check}")
    return checks


def rule_for(tags: str | None) -> dict[str, Any] | None:
    """The check for a bottle, from its tags as eLabFTW sends them ("Flammable|Peroxide former: B")."""
    names = set((tags or "").split("|"))
    return next((rule for rule in rules() if rule["tag"] in names), None)


def add_months(start: date, months: int) -> date:
    """The same day `months` later (the 31st becomes the month's last day if needed)."""
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def is_check_step(step: dict[str, Any]) -> bool:
    """Whether a step is one of our routine checks (from any rule)."""
    return any((step.get("body") or "").startswith(rule["step"]) for rule in rules())


def open_check_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The routine-check steps that are not ticked yet."""
    return [s for s in steps if not s.get("finished") and is_check_step(s)]


def schedule(rm: Resource_Manager, item_id: int, rule: dict[str, Any], start: date) -> date:
    """Adds the rule's step to the bottle, due `every_months` after start.
        :return: The due date."""
    due = add_months(start, rule["every_months"])
    step_id = rm.add_step(item_id, f"{rule['step']}, due {due.isoformat()}")
    rm.set_step(item_id, step_id, {"deadline": f"{due.isoformat()} 09:00:00"})
    return due
