# eln_server

Unified server for the DDOM Lab's custom ELN (eLabFTW) tooling. Consolidates the
former `eln_web_backend`, `eln_packages_backend`, and `eln_packages_common`
repositories into one Flask application: the web interface, the eLab API
wrapper, and the automations (autofill, label generation, RDKit images,
peroxide-former Slack reminders) all live here and run through the server.

To install an eLabFTW instance, follow the eLabFTW installation instructions at https://doc.elabftw.net/docs/category/installation/ 

<img width="1904" height="1014" alt="image" src="https://github.com/user-attachments/assets/aec601f7-02c2-4f06-8ca8-97bc39e99d4d" />

## Features
- Keyboard and QR scanner-accessible user interface
- Inventory management actions
  - Resource creation
  - Marking open (and recording open date)
  - Marking empty
  - Assosciating Resources with Experiments
  - Generating PDF labels for printing
  - Generating custom labels
  - Performing 'batch actions' (above actions taken on multiple items at once)
- ELN Automations
  - Autofilling Resource information from CAS (hazards, molecular weight, RDKit image, SMILES, etc.)
  - Reminders to check peroxide formers with formatted list of peroxide formers


## Layout

| Directory | Contents |
|---|---|
| `app.py` | Flask entry point; registers blueprints (gunicorn target `app:app`) |
| `eln_common/` | eLab API wrapper (`Resource_Manager`, `config`, `fill_info`) — formerly `eln_packages_common` |
| `automations/` | autofill, label generation, RDKit images, peroxide checks, Slack bot — formerly `eln_packages_backend` |
| `web/` | Flask blueprints: `interface` (the UI routes) and `automation_api` (`/api/...`) |
| `static/` | Web UI pages and label templates |
| `scripts/` | One-off maintenance scripts (inventory dumps, compound linking) |
| `client/` | Optional systemd timer client that calls the automation API on a schedule |
| `deploy/` | systemd unit for running the server with gunicorn |

## Configuration

Server settings live in `config.yaml` at the repo root (relative paths resolve
from there): the instance URLs (`eln_url`, `eln_web_url` — required),
`printer_path`, `auto_upload_labels`, and the team-specific status/category
IDs (`status_open`, `status_empty`, `chemical_categories`,
`label_date_categories`). The ID settings can also be set from dropdowns at
`/settings_interface`, which reads your team's actual lists from the eLabFTW
API and writes the choices back to `config.yaml`; instructions for looking the
IDs up manually are in the file's comments.

Secrets are kept separately in a gitignored `secrets.yaml` at the repo root —
copy `secrets.example.yaml` and fill in `eln_api_key` (scripts only) and
`slack_bot_token`. Secrets are read lazily, so the server can start before the
file exists and picks up changes without a restart.

Slack reporting is off unless `slack_enabled: true` is set in `config.yaml`,
with your workspace's channel IDs under `slack_channels` (see `config-ex.yaml`);
when disabled, the automations write their reports to the server log instead.

## Authentication

Generate keys using eLabFTW (https://doc.elabftw.net/docs/usage/api/). 

Actions taken through the web interface (creating resources, marking open/empty, changing location, etc.) use a user-provided API key, stored as a cookie on-device. This provides authentication for user-prompted actions.

Automated actions executed by the services in `client/`, as well as the one-off maintenance scripts stored in `scripts/` use the key provided in `secrets.yaml`. 
A generic "Automations" ELN account can be created and managed by an admin to generate API keys for these actions (that way they are not tied to a specific user).
The Slack bot token is also server-side: set `slack_bot_token` in `secrets.yaml`.

## Automation API

- `POST /api/autofill` — PubChem info fill, RDKit image (and, legacy, label upload).
  Optional JSON body: `{"id": 123}` for one item, or
  `{"start": 0, "end": null, "size": 5, "force": false, "info": true, "label": true, "image": true}`
  (defaults shown, autofills the 5 most recently modified Resources with IDs between 0 and `null` (infinity)). Errors are reported to the Slack error channel, like the old `main.py`.
- `POST /api/check_peroxides` — checks the inventory against the class A–D
  peroxide-former lists and sends Slack reminders. Returns match counts.

The `/add_resource` UI route also triggers an autofill of the new item in
the background, so info/images appear immediately after creation.

Label printing (`/print`) generates the PDF on the fly from the item's current
data. Attaching a `label.pdf` upload to each resource during autofill is a
legacy feature, disabled by default; set `auto_upload_labels: true` in
`config.yaml` to re-enable it (the `label` flag in the autofill body is
ignored unless it is set).

## Running the server

Dependencies are managed with [uv](https://docs.astral.sh/uv/) in a local
`.venv` (gitignored):

```bash
uv venv                                        # create .venv
uv pip install -r requirements.txt
uv run python app.py                           # dev
uv run gunicorn -w 2 -b 0.0.0.0:5000 app:app   # prod
```

Install `deploy/eln-server.service` (edit paths if the
checkout isn't `/usr/share/applications/eln_server`):

```bash
sudo cp deploy/eln-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now eln-server
```

### PTH blueprint

The PTH tracker is a separate project (https://github.com/ddomlab/pth_analysis). If it is available in the environment, it is started on the `/pth` endpoint, otherwise it is ignored.

## Timed automations (optional client)

The systemd timers (in `client/`) execute the automated actions. They can be automatically installed with the `install.sh` script in `client/`

This installs `eln-autofill.timer` (every 10 minutes — adjust `OnCalendar` to
taste, including excluding backup windows) and `eln-peroxide-check.timer`
(May 1 and Nov 1). The key is stored at `/etc/eln-client/api_key`; the server
URL is set via `ELN_SERVER_URL` in the `.service` files.
