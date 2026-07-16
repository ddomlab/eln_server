#!/bin/bash
# Installs the optional ELN timer client: copies the client script to
# /opt/eln-client, installs the systemd service/timer units, and enables them.
# Run as root from this directory. Re-running updates everything in place.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run as root (sudo ./install.sh)" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEY_FILE=/etc/eln-client/api_key

install -d /opt/eln-client
install -m 755 "$SCRIPT_DIR/eln_timer_client.py" /opt/eln-client/
install -m 644 "$SCRIPT_DIR"/eln-autofill.{service,timer} /etc/systemd/system/
install -m 644 "$SCRIPT_DIR"/eln-peroxide-check.{service,timer} /etc/systemd/system/

if [[ ! -f $KEY_FILE ]]; then
    SECRETS_FILE="$SCRIPT_DIR/../secrets.yaml"
    if [[ ! -f $SECRETS_FILE ]]; then
        echo "No $SECRETS_FILE found; set eln_api_key there and re-run." >&2
        exit 1
    fi
    key=$(sed -n 's/^eln_api_key:[[:space:]]*"\{0,1\}\([^"#]*[^"#[:space:]]\)"\{0,1\}[[:space:]]*$/\1/p' "$SECRETS_FILE")
    if [[ -z $key ]]; then
        echo "eln_api_key is empty in $SECRETS_FILE; fill it in and re-run." >&2
        exit 1
    fi
    install -d -m 700 /etc/eln-client
    printf '%s\n' "$key" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    echo "Wrote $KEY_FILE"
fi

systemctl daemon-reload
systemctl enable --now eln-autofill.timer eln-peroxide-check.timer

echo
echo "Installed. Check status with:"
echo "  systemctl list-timers 'eln-*'"
echo "To point at a non-local server, edit ELN_SERVER_URL in"
echo "  /etc/systemd/system/eln-autofill.service and eln-peroxide-check.service,"
echo "then: systemctl daemon-reload"
