import requests

import eln_common.config as config

# Logical channel names, mapped to the workspace's actual channel IDs by the
# slack_channels section of config.yaml (see config-ex.yaml).
# general bot messages
DEFAULT_CHANNEL: str = "default"
# error reports from the automations
ERROR_CHANNEL: str = "error"
# peroxide former reminders
PEROXIDE_CHANNEL: str = "peroxide"

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
    requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=headers,
        json={"channel": channel_id, "text": message},
    )


if __name__ == "__main__":
    # Test the bot by sending a message to the default channel
    send_message("Hello from the ELN bot! This is a test message.")
    print("Message sent successfully.")
