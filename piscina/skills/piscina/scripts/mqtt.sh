#!/bin/sh
# MQTT helper against the broker on the Pi (eclipse-mosquitto container, port 1883 published on the host).
#   mqtt.sh pub <topic> <payload>          publish once (user poolmqtt, read/write)
#   mqtt.sh sub <topic> [count] [timeout]  subscribe (default 1 message, 70 s; user poolread, read-only)
#   mqtt.sh np  "<Backlog>"                send a Tasmota/NeoPool Backlog to the Atom and print RESULTs
# Examples:
#   mqtt.sh sub tele/aquarite/SENSOR            # full NeoPool telemetry (60 s)
#   mqtt.sh sub tele/aquarite/FAST              # poller 5 s: relay_raw, acid, FL1, gh, rails
#   mqtt.sh pub pool/cmd/input_number/pool_chlor_hours 13.25
#   mqtt.sh np "NPRead 0x0434,9; NPRead 0x050F,1"
# Credentials never leave the Pi: the host clients mosquitto_sub/mosquitto_pub read ~/.config/mosquitto_sub
# (poolread) and ~/.config/mosquitto_pub (poolmqtt) there; ~/.config/pool/secrets.env is the fallback used
# when the host clients are missing (then the container clients are used).
DIR=$(cd "$(dirname "$0")" && pwd)
# Shell prelude run on the Pi: defines msub/mpub using host clients or the container fallback.
PRE='if command -v mosquitto_sub >/dev/null 2>&1; then msub() { mosquitto_sub "$@"; }; mpub() { mosquitto_pub "$@"; }; else . ~/.config/pool/secrets.env; msub() { sudo docker exec mosquitto mosquitto_sub -h localhost -u "$MQTT_RO_USER" -P "$MQTT_RO_PW" "$@"; }; mpub() { sudo docker exec mosquitto mosquitto_pub -h localhost -u "$MQTT_USER" -P "$MQTT_PW" "$@"; }; fi;'
case "$1" in
  pub) "$DIR/pi.sh" "$PRE mpub -t '$2' -m '$3'" ;;
  sub) "$DIR/pi.sh" "$PRE msub -t '$2' -C ${3:-1} -W ${4:-70}" ;;
  np)  "$DIR/pi.sh" "$PRE msub -t stat/aquarite/RESULT -C 60 -W 12 > /tmp/np_res.txt & S=\$!; sleep 1; mpub -t cmnd/aquarite/Backlog -m '$2'; wait \$S; grep -v -E '\"Address\":\"0x0100\"|\"Address\":\"0x0020\"|Var2' /tmp/np_res.txt" ;;
  *) echo "usage: mqtt.sh pub|sub|np ..."; exit 1 ;;
esac
