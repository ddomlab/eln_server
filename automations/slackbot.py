import requests

import eln_common.config as config

# channel ID of the eln_bot channel, can be found by clicking "view channel details"
DEFAULT_CHANNEL: str = "C093HPVRLKD"
# channel for error reports from the automations
ERROR_CHANNEL: str = "G093HPVQ9AP"
# channel for peroxide former reminders
PEROXIDE_CHANNEL: str = "C07SSMMU9E1"

BOT_TOKEN_PATH: str = config.SLACK_BOT_TOKEN_PATH


def _get_token() -> str:
    # loaded lazily so the server can start (and non-Slack features work)
    # even if the token file hasn't been placed yet
    with open(BOT_TOKEN_PATH) as file:
        return file.read().rstrip()


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
