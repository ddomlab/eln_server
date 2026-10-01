# eln_server

Unified server for the DDOM Lab's custom ELN (eLabFTW) tooling. Consolidates the
former `eln_web_backend`, `eln_packages_backend`, and `eln_packages_common`
repositories into one Flask application: the web interface, the eLab API
wrapper, and the automations (label generation, RDKit images,
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
  - Reminders to check peroxide formers with formatted list of peroxide formers


## Layout

| Directory | Contents |
|---|---|
| `app.py` | Flask entry point; registers blueprints (gunicorn target `app:app`) |
| `eln_common/` | eLab API wrapper (`Resource_Manager`, `config`, `fill_info`) — formerly `eln_packages_common` |
| `automations/` | label generation, RDKit images, peroxide checks, Slack bot — formerly `eln_packages_backend` |
| `web/` | Flask blueprints: `interface` (the UI routes) and `automation_api` (`/api/...`) |
| `static/` | Web UI pages and label templates |
| `scripts/` | One-off maintenance scripts (inventory dumps, compound linking) |
| `client/` | Optional systemd timer client that calls the automation API on a schedule |
| `deploy/` | systemd unit for running the server with gunicorn |

## Configuration

Server settings live in `config.yaml` at the repo root (relative paths resolve
from there): the instance URLs (`eln_url`, `eln_web_url` — required),
`printer_path`, and the team-specific status/category
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

- `POST /api/check_peroxides` — checks the inventory against the class A–D
  peroxide-former lists and sends Slack reminders. Returns match counts.

Label printing (`/print`) generates the PDF on the fly from the item's current
data.

There is no autofill any more (removed 2026-10): chemical details live on the
compound each resource is linked to, instead of being copied from PubChem into
every resource's fields.

## Running the server

### With Docker (the lab server)

`deploy/compose.yaml` builds the image from this checkout and runs it with
`config.yaml` and `secrets.yaml` mounted from the repo root (they are never
baked into the image). The container joins the shared `lab-net` network, where
the edge proxy reaches it at `http://eln-server:5000`; the lab's address stays
`https://eln.ddomlab.org:5000` (Caddy sends `/pth/...` to the PTH container and
everything else here). It also listens on `127.0.0.1:5001` for the timer client
on the same host.

```bash
git clone https://github.com/ddomlab/eln_server.git /opt/eln-server
cd /opt/eln-server
cp config-ex.yaml config.yaml                                    # set eln_url, eln_web_url, IDs
cp secrets.example.yaml secrets.yaml && chmod 600 secrets.yaml   # fill in the Slack token etc.
cd deploy && sudo docker compose up -d --build
sudo docker compose ps                                           # expect "healthy"
```

The container runs as uid 1000, so both files must be readable by that user
(and `config.yaml` writable, since `/settings_interface` saves to it).
Update: `git pull && sudo docker compose up -d --build`.
`constraints.txt` pins the Python package versions the image installs.

### Without Docker

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

This installs `eln-peroxide-check.timer` (May 1 and Nov 1), and removes the old
`eln-autofill.timer` from hosts that still have it. The key is stored at `/etc/eln-client/api_key`; the server
URL is set via `ELN_SERVER_URL` in the `.service` files.
Pass it at install time to skip editing them; with the Docker deploy on the same
host that's the local port:

```bash
cd client && sudo ELN_SERVER_URL=http://127.0.0.1:5001 ./install.sh
```
