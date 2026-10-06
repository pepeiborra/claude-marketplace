#!/bin/sh
# Run a command on the pool Raspberry Pi (HA + mosquitto + poller). Passwordless sudo.
# Requires a `Host pi` alias in ~/.ssh/config (user, address, host-key alias live there, not in the plugin).
# Usage: pi.sh '<remote shell command>'
exec ssh pi "$@"
