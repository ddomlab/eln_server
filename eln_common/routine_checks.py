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
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

import eln_common.config as config
from eln_common.resourcemanage import Resource_Manager

RULES_PATH = Path(__file__).resolve().parent.parent / "automations" / "routine_checks.yaml"
# the due date in a step's text: "Test for peroxides (class B), due 2027-04-06"
DUE_DATE = re.compile(r"\bdue (\d{4}-\d{2}-\d{2})\b")


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


def bottles_to_check(rm: Resource_Manager, empty_status: int) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """The resources with a routine check (peroxide-former bottles, instruments with a
    maintenance interval) that are still in use (not Empty, not archived), each with
    its rule: [(item, rule)], items as eLabFTW lists them."""
    bottles, seen = [], set()
    for rule in rules():
        for item in rm.items_with_tag(rule["tag"]):
            # state 1 = normal (2 = archived, 3 = deleted)
            if item["id"] in seen or item.get("state") != 1 or item.get("status") == empty_status:
                continue
            seen.add(item["id"])  # a bottle with two check tags is listed once, like rule_for
            bottles.append((item, rule))
    return bottles


def due_checks(rm: Resource_Manager, bottles: list[tuple[dict[str, Any], dict[str, Any]]],
               today: date) -> dict[str, list]:
    """
    Sorts the bottles' unticked check steps by their due date: overdue (before today)
    and due (from today to the end of this month). Later ones wait for next month's run.
        :param bottles: From bottles_to_check.
        :return: {"overdue": [...], "due": [...], "problems": [...]}, entries as
            {id, title, check, due (YYYY-MM-DD), place}, earliest first; problems are
            bottles whose steps or due date could not be read.
    """
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    report: dict[str, list] = {"overdue": [], "due": [], "problems": []}
    for item, _rule in bottles:
        label = f"#{item['id']} {item.get('title', '')}".strip()
        try:
            steps = open_check_steps(rm.get_steps(item["id"]))
        except Exception as e:
            report["problems"].append(f"{label}: could not read its steps: {e}")
            continue
        for step in steps:
            body = step.get("body") or ""
            match = DUE_DATE.search(body)
            try:
                due = date.fromisoformat(match.group(1)) if match else None
            except ValueError:  # e.g. "due 2027-02-30"
                due = None
            if due is None:
                report["problems"].append(f'{label}: no due date in "{body}"')
                continue
            if due > month_end:
                continue
            report["overdue" if due < today else "due"].append({
                "id": item["id"], "title": item.get("title", ""),
                "check": next(rule["step"] for rule in rules() if body.startswith(rule["step"])),
                "due": due.isoformat(), "place": place(rm, item["id"]),
            })
    for group in ("overdue", "due"):
        report[group].sort(key=lambda entry: (entry["due"], entry["id"]))
    return report


def place(rm: Resource_Manager, item_id: int) -> str:
    """Where a bottle is kept, as its storage path ("Room 3057 > Front hood > ..."); empty
    for a resource without one (instruments have no storage place)."""
    try:
        containers = rm.get_item(item_id).get("containers") or []
    except Exception:
        return "place unknown (could not read it)"
    return "; ".join(c.get("full_path") or c.get("storage_name") or "?" for c in containers)


def format_report(report: dict[str, list], today: date) -> str:
    """The Slack message for a due_checks report: overdue, due this month and any
    bottles that could not be checked, or "Nothing due this month"."""
    lines = [f"*ELN maintenance: {today:%B %Y}*"]
    for group, heading in (("overdue", "*Overdue*"), ("due", "*Due this month* (please do these now)")):
        if report[group]:
            lines.append(heading)
            lines += [f"• <{config.item_web_url(e['id'])}|#{e['id']}> {slack_text(e['title'])}: "
                      f"{slack_text(e['check'])}, due {e['due']}" + (f", {slack_text(e['place'])}" if e["place"] else "")
                      for e in report[group]]
    if report["problems"]:
        lines.append("*Could not check*")
        lines += [f"• {slack_text(problem)}" for problem in report["problems"]]
    if report["overdue"] or report["due"]:
        lines.append("_Done? Scan it + Tested. Bottle used up? Scan + Mark Empty._")
    elif not report["problems"]:
        lines.append("Nothing due this month ✓")
    return "\n".join(lines)


def slack_text(text: str) -> str:
    """Text as Slack shows it literally: &, < and > are its formatting characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def schedule(rm: Resource_Manager, item_id: int, rule: dict[str, Any], start: date) -> date:
    """Adds the rule's step to the bottle, due `every_months` after start.
        :return: The due date."""
    due = add_months(start, rule["every_months"])
    step_id = rm.add_step(item_id, f"{rule['step']}, due {due.isoformat()}")
    rm.set_step(item_id, step_id, {"deadline": f"{due.isoformat()} 09:00:00"})
    return due
