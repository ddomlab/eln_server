import requests

import eln_common.config as config

# Logical channel names, mapped to the workspace's actual channel IDs by the
# slack_channels section of config.yaml (see config-ex.yaml).
# general bot messages
DEFAULT_CHANNEL: str = "default"
# error reports from the automations
ERROR_CHANNEL: str = "error"
# peroxide former reminders (the old twice-a-year check)
PEROXIDE_CHANNEL: str = "peroxide"
# monthly routine-check reminders (peroxide tests; later instrument checks)
MAINTENANCE_CHANNEL: str = "maintenance"

def _get_token() -> str:
    # loaded lazily so the server can start (and non-Slack features work)
    # even if the secret hasn't been filled in yet
    token = config.get_secret("slack_bot_token")
    if not token:
        raise ValueError(f"No slack_bot_token set in {config.SECRETS_PATH}")
    return token


# Very simple bot. Sends a message in its designated channel when called.
# `channel` is one of the logical names above; if the lab isn't on Slack
# (slack_enabled: false, the default), the message goes to the server log.
def send_message(message: str, channel: str = DEFAULT_CHANNEL):
    if not config.setting("slack_enabled", False):
        print(f"[slack disabled] {channel}: {message}")
        return
    channels = config.setting("slack_channels", {}) or {}
    channel_id = channels.get(channel) or channels.get(DEFAULT_CHANNEL)
    if not channel_id:
        print(f"[slack] no channel id for '{channel}' in slack_channels "
              f"(config.yaml); message not sent: {message}")
        return
    headers = {
        "Authorization": "Bearer " + _get_token(),
        "Content-Type": "application/json",
    }
    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=headers,
        json={"channel": channel_id, "text": message},
        timeout=30,
    )
    _check_reply(response, channel)


def _check_reply(response: requests.Response, channel: str) -> None:
    """Raises if Slack did not post the message. Slack answers 200 even when it
    refuses one (e.g. the bot isn't in the channel), with {"ok": false, "error": ...}."""
    try:
        reply = response.json()
    except ValueError:
        reply = {}
    if not response.ok or not reply.get("ok"):
        raise RuntimeError(f"Slack did not post the message to '{channel}': "
                           f"{reply.get('error') or f'HTTP {response.status_code}'}")


if __name__ == "__main__":
    # Test the bot by sending a message to the default channel
    send_message("Hello from the ELN bot! This is a test message.")
    print("Message sent successfully.")
