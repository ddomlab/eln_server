# Lab-portability report

Audit of everything that would not "just work" for another lab installing
eln_server against their own eLabFTW instance. Each item notes where it lives,
what breaks, and the rough effort to make it flexible. Items another lab could
reasonably be told to replicate are marked **(convention)** — you may choose
to document them as requirements instead of fixing them.

## 1. Hardcoded URLs — FIXED

All resolved (2026-07-15): `config.yaml` now has **required** `eln_url` and
`eln_web_url` keys — no in-code defaults; the server raises at startup if
either is missing. `config.item_web_url(id)` builds resource links for labels,
`/create_label`, and Slack reports; the static UI fetches the web URL from the
new `GET /eln_config` endpoint, and the QR-scan input now recognizes item
links from any eLabFTW domain.

| Where | What | Status |
|---|---|---|
| `eln_common/config.py` | Default `eln_url` was `https://eln.ddomlab.org/api/v2` | **Fixed** — required key, no default. |
| `automations/labels/generate_label.py` | QR code on printed labels | **Fixed** — `config.item_web_url()`. |
| `web/interface.py` (`/create_label`) | "Resource" QR type URL | **Fixed** — same. |
| `automations/autofill.py` | Slack error message links | **Fixed** — same. |
| `static/index.html` | QR-scan input only recognized `eln.ddomlab.org` URLs | **Fixed** — accepts any `http…id=` link. |
| `static/index.html` | "open page" command | **Fixed** — uses `/eln_config`. |
| `static/render_form.js` | "generate a key at…" alert | **Fixed** — uses `/eln_config`. |
| `automations/autofill.py` | Docstring Slite link | **Fixed** — removed. |
| `static/*.html` | Google Fonts + qrcodejs/qrcode CDN imports | **Open (optional)** — not lab-specific, but the UI needs internet; vendor the assets for air-gapped labs. |

## 2. Hardcoded categories and statuses — FIXED

All resolved (2026-07-15). Team-specific IDs now live in `config.yaml`
(`status_open`, `status_empty`, `chemical_categories`,
`label_date_categories`), with instructions in the file for looking the IDs
up. They are re-read on every request, so edits apply to all gunicorn workers
without a restart. A settings page at `/settings_interface` reads the team's
actual status/category lists from the eLabFTW API (via the new `/statuses`
and `/categories` endpoints) and saves selections back to `config.yaml`
(POST `/settings`, which requires a working API key).

| Where | Assumption | Status |
|---|---|---|
| `web/interface.py` (`/mark_open`, `/change_location`) | status `4` = "Opened" | **Fixed** — `status_open` config key. |
| `web/interface.py` (`/mark_empty`) | status `5` = "Empty" | **Fixed** — `status_empty`. |
| `automations/autofill.py` | categories `2`,`3` get PubChem info + RDKit images | **Fixed** — `chemical_categories`. |
| `automations/labels/generate_label.py` | categories `2–4` get a Received date on labels | **Fixed** — `label_date_categories`. |
| `static/render_form.js` | hardcoded category dropdown | **Fixed** — populated from `/categories`. |
| `web/interface.py` (`/template`) | items-types list indexed by position | **Fixed** — matched on `id`; unknown ids return 404. |
| `eln_common/resourcemanage.py` | DDOM category mapping in docstring | **Fixed** — genericized. |

## 3. Lab-specific instructions / content

| Where | What | Notes |
|---|---|---|
| `README.md` | DigitalOcean box, `/usr/share/applications/eln_server` checkout path, "remove the old crontab entries" migration notes | Rewrite as generic install instructions with DDOM specifics in a separate "our deployment" section. **Low.** |
| `deploy/eln-server.service` | Absolute gunicorn path `/usr/share/applications/eln_server/.venv/bin/gunicorn` and WorkingDirectory | Already flagged "adjust paths"; consider an install script that templates them. **Low.** |
| `client/eln-peroxide-check.timer` | Peroxide checks on May 1 / Nov 1 — that cadence is DDOM lab policy | Document as an example schedule. **(convention)** |
| `automations/peroxides/check_peroxides.py:17` | NIH guidance link in the reminder message | Generic safety reference, fine to keep. |
| `static/*.html` UI text | Voice commands, page copy | English-only but otherwise generic. |

## 4. Other lab-specific details that won't track ELN changes

### Extra-field name conventions (convention, but worth documenting)
The code expects resources to carry specific extra fields, by exact name and
capitalization. Another lab must define their templates the same way or these
features break:

- `Opened` — `/mark_open`. **Fixed (2026-07-15)** — a missing field now
  returns a clean 400 explaining the template must define an `Opened` extra
  field, instead of an unhandled KeyError → HTTP 500.
- `Location` — `/change_location`. **Fixed (2026-07-15)** — same clean-400
  treatment. `/get_locations` reads each template's `Location.options` (that
  part is dynamic and degrades gracefully)
- `Received` — printed labels (now degrades to a blank date)
- `CAS`, `SMILES`, `Full name`, `Molecular Weight`, `Pubchem Link`,
  `Hazards Link` — autofill/`/search`. **Fixed (2026-07-15)** — `fill_info`
  now creates `Full name` if absent, like it already did for the other fields.
- `Room`, `Location`, `CAS`, `Quantity`/`Quantity Units` — peroxide checks and
  the `scripts/` one-offs assume these DataFrame columns exist; items missing
  them make `get_items_df` produce NaN columns or KeyErrors. **(convention)**

Suggested cheap win (remaining): a "required template fields" section in the
README.

### Slack integration — FIXED
Both resolved (2026-07-15): the three channel IDs now live in `config.yaml`
under `slack_channels: {default, error, peroxide}` (call sites pass those
logical names), and Slack is off unless `slack_enabled: true` is set —
disabled or unconfigured channels turn `send_message` into a server-log line.

### Autofill ID threshold — REMOVED
Removed entirely (2026-07-15): `autofill` and `POST /api/autofill` now default
to `start=0`, and the timer client no longer sends `start: 300`. A range can
still be passed explicitly when needed.

### Labels / printer
- `automations/labels/style.css` — 62×18 mm label geometry for our specific
  label stock; `printer_path` is configurable but the dimensions/layout are
  not. Ship alternative templates or document the files to edit.
  **(convention)**
- `static/Flex_Label.html` + `flex_style.css` — same for the custom-label page.

### Peroxide former lists
- `automations/peroxides/Chemical List PEROXIDES{A-D}-2025-04-21.csv` —
  filenames embed a snapshot date; the data is external (not lab-specific) but
  static. Fine to ship, but document how to refresh, or glob the filename
  instead of hardcoding the date. **Low.**

### Web UI plumbing
- `static/render_form.js:1` — `BASE_URL = ""` ("adjust as needed") is fine for
  same-origin serving; document that.
- `@cross_origin(origins="http://localhost:8000")` on every interface route
  (`web/interface.py`) — dev leftover; harmless same-origin but should be
  removed or made configurable for anyone serving the UI separately. **Low.**

### Miscellaneous
- `pth_data.db` sits in the repo root — data for the optional PTH project;
  should not ship in a general release (add to `.gitignore`).
- `tests/conftest.py` defaults to a key file path on your dev machine
  (`.../MEDUSA/config/apikey.yaml`); harmless (env var and `secrets.yaml`
  fallbacks exist) but worth knowing.
- `eln_common/resourcemanage.py:255` (`get_items_df`) — assumes any field with
  a `unit` key has a non-empty `units` list; another lab's templates could
  trip this. Generic robustness, not DDOM-specific.

## Suggested priority if you make it flexible

1. ~~**`eln_web_url` config key**~~ — **done** (see section 1).
2. ~~**Category/status config keys**~~ — **done** (see section 2), plus a
   `/settings_interface` page to set them from API-fed dropdowns. The 300 ID
   threshold has since been removed outright (see section 4).
3. ~~**`/template` lookup by id, not list index**~~ — **done**.
4. ~~**Slack channels + enable switch in config.**~~ — **done** (see
   section 4).
5. ~~**Category dropdown populated from the API**~~ — **done**.
6. **Document the required extra-field names** in the README — the clean-400
   half is **done** for `/mark_open`/`/change_location`.
