# eln_server

Unified server for the DDOM Lab's custom ELN (eLabFTW) tooling. Consolidates the
former `eln_web_backend`, `eln_packages_backend`, and `eln_packages_common`
repositories into one Flask application: the web interface, the eLab API
wrapper, and the automations (autofill, label generation, RDKit images,
peroxide-former Slack reminders) all live here and run through the server.

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

## Authentication

Every route acts as the eLabFTW API key the caller provides — there is no
server-held key for request handling.

- Web UI: the `apiKey` cookie (unchanged from `eln_web_backend`).
- API clients / timer client: the `Authorization` header (a bare key or
  `Bearer <key>`).

Generate keys at https://eln.ddomlab.org/ucp.php?tab=3. The one-off scripts in
`scripts/` are the exception: they read a local `eln_common/api_key` file
(gitignored), or the path in `$ELN_API_KEY_PATH`.

The Slack bot token is server-side: place it at `automations/slack_bot_token`
or point `$SLACK_BOT_TOKEN_PATH` at it.

## Automation API

- `POST /api/autofill` — label upload, PubChem info fill, RDKit image.
  Optional JSON body: `{"id": 123}` for one item, or
  `{"start": 300, "end": null, "size": 5, "force": false, "info": true, "label": true, "image": true}`
  (defaults shown; matches the old cron behavior). Errors are reported to the
  Slack error channel, like the old `main.py`.
- `POST /api/check_peroxides` — checks the inventory against the class A–D
  peroxide-former lists and sends Slack reminders. Returns match counts.

The `/add_resource` UI route now also triggers an autofill of the new item in
the background, so labels/info/images appear immediately after creation.

## Running the server

```bash
conda env create -f environment.yml   # or: pip install -r requirements.txt
conda activate ddomlabbackend
python app.py                          # dev
gunicorn -w 4 -b 0.0.0.0:5000 app:app  # prod
```

On the DigitalOcean box, install `deploy/eln-server.service` (edit paths if the
checkout isn't `/usr/share/applications/eln_server`):

```bash
sudo cp deploy/eln-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now eln-server
```

### PTH blueprint

The PTH tracker is a separate project. If its files (`pth_server.py`, its data)
are placed next to `app.py`, its blueprint is registered automatically;
otherwise the server starts without it.

## Timed automations (optional client)

The old cron jobs (`run.sh`, `check_peroxides.sh`) are replaced by systemd
timers that call the API. On whatever machine should drive the schedule
(usually the server itself):

```bash
cd client
sudo ./install.sh   # prompts for the eLab API key to act as
```

This installs `eln-autofill.timer` (every 10 minutes — adjust `OnCalendar` to
taste, including excluding backup windows) and `eln-peroxide-check.timer`
(May 1 and Nov 1). The key is stored at `/etc/eln-client/api_key`; the server
URL is set via `ELN_SERVER_URL` in the `.service` files. Remove the old
crontab entries for `run.sh`/`check_peroxides.sh` after installing.
