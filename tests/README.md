# eln_server test suite

Two kinds of tests:

| File | What it covers | Needs |
|---|---|---|
| `test_routes_offline.py` | Routing, auth-key extraction, input validation, CAS validation, config loading, pure helpers | Nothing external |
| `test_live_eln.py` | Reads, mutations, label printing, the automation API, and `/search` against the **real** eLabFTW server (and PubChem) | An eLN API key |

Live tests are marked `@pytest.mark.live` (registered in `pytest.ini`).

## Running

```bash
pytest                  # everything (live tests skip if no key is found)
pytest -m "not live"    # offline only — safe anywhere, no key needed
pytest -m live          # live only
```

## API key for live tests

Resolved in this order (see `_load_api_key` in `conftest.py`):

1. `$ELN_TEST_API_KEY` — the key itself.
2. A yaml file at `$ELN_TEST_API_KEY_FILE` (default: `config.yaml` at the
   project root) containing an `ELN_API_KEY` or `eln_api_key` entry.
3. The `eln_api_key` entry in the project's `secrets.yaml`.

If none of these yields a key, live tests skip rather than fail.

## Safety rails

- **Slack can never be hit.** The autouse `slack_messages` fixture stubs
  `automations.slackbot.send_message` for every test and records what would
  have been sent, so tests can assert on outgoing messages.
- **Only resource 393 is mutated.** `TEST_ITEM_ID` in `conftest.py` names the
  one item the suite may touch; the `restore_item` fixture snapshots its
  metadata/status before a mutation test and restores them after.
- `/api/check_peroxides` is only tested for auth (offline): a real run would
  send reminders for every matching item in the inventory.

## Fixtures (`conftest.py`)

| Fixture | Scope | Purpose |
|---|---|---|
| `api_key` | session | The eLN key, resolved as above; skips the test if absent |
| `flask_app` | session | The Flask app with `TESTING` enabled |
| `client` | function | `flask_app.test_client()` |
| `auth_headers` | function | `Authorization: Bearer <key>` header dict |
| `live_rm` | function | A `Resource_Manager` on the test key, for live setup/teardown |
| `slack_messages` | function, autouse | Stubs Slack; yields the list of captured messages |
