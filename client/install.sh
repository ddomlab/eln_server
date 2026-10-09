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
UNITS=(eln-routine-checks)
for unit in "${UNITS[@]}"; do
    install -m 644 "$SCRIPT_DIR/$unit".{service,timer} /etc/systemd/system/
done

# optional: point the timers at a server other than the default in the .service files,
# e.g. sudo ELN_SERVER_URL=http://127.0.0.1:5001 ./install.sh (the Docker deploy's local port)
if [[ -n ${ELN_SERVER_URL:-} ]]; then
    for unit in "${UNITS[@]}"; do
        sed -i "s|^Environment=ELN_SERVER_URL=.*|Environment=ELN_SERVER_URL=$ELN_SERVER_URL|" \
            "/etc/systemd/system/$unit.service"
    done
    echo "Timers will call $ELN_SERVER_URL"
fi

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

# timers that were replaced: take them off hosts that still have them.
#   eln-autofill: removed (compounds now hold the chemical details)
#   eln-peroxide-check: the twice-a-year list, replaced by the monthly eln-routine-checks
for old in eln-autofill eln-peroxide-check; do
    if [[ -f /etc/systemd/system/$old.timer ]]; then
        systemctl disable --now "$old.timer" || true
        rm -f "/etc/systemd/system/$old.service" "/etc/systemd/system/$old.timer"
        echo "Removed the old $old timer"
    fi
done

systemctl daemon-reload
for unit in "${UNITS[@]}"; do
    systemctl enable --now "$unit.timer"
done

echo
echo "Installed. Check status with:"
echo "  systemctl list-timers 'eln-*'"
echo "To point at a non-local server, edit ELN_SERVER_URL in"
echo "  /etc/systemd/system/eln-*.service,"
echo "then: systemctl daemon-reload"
