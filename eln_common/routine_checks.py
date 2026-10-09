"""
Routine checks on bottles (e.g. testing peroxide formers) and instrument
maintenance, kept as eLabFTW steps.

A bottle with a tag listed in automations/routine_checks.yaml gets a step such as
"Test for peroxides (class B), due 2027-04-06" when it is marked open. An
instrument with a tag like "Maintenance: every 45 days" (any number of days, weeks
or months, see maintenance_rule) gets "Instrument maintenance (every 45 days), due
..." when it is created. "Tested" ticks the step and adds the next one; "Mark
Empty" closes a bottle's (see bottle_actions). The due date is written into the
step's text as well as its deadline, because eLabFTW clears the deadline when a
step is ticked.
"""

import calendar
import functools
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from eln_common.resourcemanage import Resource_Manager

RULES_PATH = Path(__file__).resolve().parent.parent / "automations" / "routine_checks.yaml"

# instrument maintenance: "Maintenance: every 45 days", "... every 1 month"
MAINTENANCE_TAG = re.compile(r"^Maintenance: every (\d+) (day|week|month)s?$")
MAINTENANCE_STEP = "Instrument maintenance"
# the longest interval for each unit (about 10 years), so a typo can't set a due date centuries away
MAX_EVERY = {"day": 3650, "week": 520, "month": 120}


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


def every_text(every: int, unit: str) -> str:
    """The interval in words: "every 45 days", "every 1 month"."""
    return f"every {every} {unit}{'' if every == 1 else 's'}"


def maintenance_tag(every: int, unit: str) -> str:
    """The tag for an instrument's maintenance interval, e.g. (45, "day") -> "Maintenance: every 45 days"."""
    return f"Maintenance: {every_text(every, unit)}"


def maintenance_rule(tag: str) -> dict[str, Any] | None:
    """The check for a maintenance tag: {tag, step, every, unit}; None if the tag isn't one
    (or its interval is 0 or too long)."""
    match = MAINTENANCE_TAG.match(tag)
    if not match:
        return None
    every, unit = int(match[1]), match[2]
    if not 1 <= every <= MAX_EVERY[unit]:
        return None
    return {"tag": tag, "step": f"{MAINTENANCE_STEP} ({every_text(every, unit)})", "every": every, "unit": unit}


def rule_for(tags: str | None) -> dict[str, Any] | None:
    """The check for a bottle or instrument, from its tags as eLabFTW sends them
    ("Flammable|Peroxide former: B"): a rule from the file, else a maintenance tag."""
    names = (tags or "").split("|")
    rule = next((rule for rule in rules() if rule["tag"] in names), None)
    return rule or next((r for r in map(maintenance_rule, names) if r), None)


def add_months(start: date, months: int) -> date:
    """The same day `months` later (the 31st becomes the month's last day if needed)."""
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def due_date(start: date, rule: dict[str, Any]) -> date:
    """When the rule's next check is due: `every` days, weeks or months after start
    (rules from the file count in months: every_months)."""
    if "every_months" in rule:
        return add_months(start, rule["every_months"])
    if rule["unit"] == "month":
        return add_months(start, rule["every"])
    return start + timedelta(days=rule["every"] * (7 if rule["unit"] == "week" else 1))


def is_check_step(step: dict[str, Any]) -> bool:
    """Whether a step is one of our routine checks (from any rule, or instrument maintenance)."""
    body = step.get("body") or ""
    return body.startswith(f"{MAINTENANCE_STEP} (") or any(body.startswith(rule["step"]) for rule in rules())


def open_check_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The routine-check steps that are not ticked yet."""
    return [s for s in steps if not s.get("finished") and is_check_step(s)]


def schedule(rm: Resource_Manager, item_id: int, rule: dict[str, Any], start: date) -> date:
    """Adds the rule's step to the bottle or instrument, due one interval after start.
        :return: The due date."""
    due = due_date(start, rule)
    step_id = rm.add_step(item_id, f"{rule['step']}, due {due.isoformat()}")
    rm.set_step(item_id, step_id, {"deadline": f"{due.isoformat()} 09:00:00"})
    return due
