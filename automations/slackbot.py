import requests

import eln_common.config as config

# channel ID of the eln_bot channel, can be found by clicking "view channel details"
DEFAULT_CHANNEL: str = "C093HPVRLKD"
# channel for error reports from the automations
ERROR_CHANNEL: str = "G093HPVQ9AP"
# channel for peroxide former reminders
PEROXIDE_CHANNEL: str = "C07SSMMU9E1"

def _get_token() -> str:
    # loaded lazily so the server can start (and non-Slack features work)
    # even if the secret hasn't been filled in yet
    token = config.get_secret("slack_bot_token")
    if not token:
        raise ValueError(f"No slack_bot_token set in {config.SECRETS_PATH}")
    return token


# Very simple bot. Sends a message in its designated channel when called.
def send_message(message: str, channel: str = DEFAULT_CHANNEL):
    headers = {
        "Authorization": "Bearer " + _get_token(),
        "Content-Type": "application/json",
    }
    requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=headers,
        json={"channel": channel, "text": message},
    )


if __name__ == "__main__":
    # Test the bot by sending a message to the default channel
    send_message("Hello from the ELN bot! This is a test message.")
    print("Message sent successfully.")
