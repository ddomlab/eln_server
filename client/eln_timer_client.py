#!/usr/bin/env python3
"""
Timer client for the ELN server automations.

Makes an authenticated POST to one of the server's automation endpoints. Meant
to be run by the systemd timers in this directory (replacing the old cron jobs),
but can be run by hand:

    eln_timer_client.py autofill
    eln_timer_client.py check_peroxides

Uses only the Python standard library, so it needs no environment to run.

Configuration (environment variables, set in the systemd unit or shell):
    ELN_SERVER_URL     base URL of the server (default http://localhost:5000)
    ELN_API_KEY_FILE   path to a file containing the eLabFTW API key to act as
                       (default /etc/eln-client/api_key)
"""
import json
import os
import sys
import urllib.request

SERVER_URL = os.environ.get("ELN_SERVER_URL", "http://localhost:5000").rstrip("/")
API_KEY_FILE = os.environ.get("ELN_API_KEY_FILE", "/etc/eln-client/api_key")

TASKS = {
    # matches the old cron behavior: autofill the 5 most recent items with id >= 300
    "autofill": {"start": 300, "size": 5, "info": True, "label": True, "image": True},
    "check_peroxides": {},
}


def run(task: str) -> int:
    if task not in TASKS:
        print(f"Unknown task '{task}'. Valid tasks: {', '.join(TASKS)}", file=sys.stderr)
        return 2
    with open(API_KEY_FILE) as f:
        key = f.read().strip()
    req = urllib.request.Request(
        f"{SERVER_URL}/api/{task}",
        data=json.dumps(TASKS[task]).encode(),
        headers={"Authorization": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            print(f"{task}: {resp.status} {resp.read().decode()}")
            return 0
    except urllib.error.HTTPError as e:
        print(f"{task} failed: {e.code} {e.read().decode()}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(run(sys.argv[1]))
