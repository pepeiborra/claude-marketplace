# Access, protocols and recipes

## Hosts and paths
- **Pi**: `ssh pi` — the alias in `~/.ssh/config` holds user, address and host-key alias, so the plugin carries no network details (passwordless sudo). Use `scripts/pi.sh '<cmd>'`.
  - HA config: `/home/pi/homeassistant/homeassistant/config/` → `configuration.yaml` (recorder excludes, lovelace dashboards), `packages/pool_scheduler.yaml`, `packages/pool_ph_alarm.yaml`, `packages/pool_lsi.yaml`, `packages/pool_alkalinity.yaml`, `pool_mqtt.yaml`, `pool-diagnostics.yaml`.
  - Compose: `cd ~/homeassistant && sudo docker compose restart homeassistant` (3–4 min). Logs: `sudo docker logs homeassistant --since 30m`.
  - Recorder DB: `home-assistant_v2.db` (sqlite, 30 days retention). Open **read-only**: `sqlite3.connect("file:...?mode=ro", uri=True)` — never `immutable=1`. Python3 is on the Pi, the `sqlite3` CLI is not.
  - Poller: `/home/pi/poolfast/poller.py`, unit `poolfast.service` (`POLL_INTERVAL=5.0`, `RETAIN_DAYS=14`), JSONL `/home/pi/poolfast/fast-YYYYMMDD.jsonl`. Health: `systemctl show poolfast -p TasksCurrent` ≈ 11.
  - Manual acid pump: `sudo docker exec mosquitto /usr/local/bin/acid_pump.sh on|off|status` (writes `0x0289=1` + `NPBit 0x010E 0 1`; `off` clears and `NPExec`).
- **Mac repo**: `~/scratch/atom-pool/` (see SKILL.md mapping). Memory: `~/.claude/projects/-Users-pepeiborra/memory/`.
- Pi memory is tight (4 GB, zram): never run `hass --script check_config` there; validate YAML on the Mac with ruby/python.

## MQTT (broker in the `mosquitto` container, port 1883 on the Pi host)
Credentials never leave the Pi. Two broker users (`passwordfile` + `aclfile` in `~/homeassistant/mosquitto/config/`, `acl_file` line in `mosquitto.conf`):
- `poolmqtt` — read/write `#`; used by HA, the Atom bridge, the poller and `mqtt.sh pub|np`.
- `poolread` — read-only (`tele/#`, `stat/#`, `pool/#`, `homeassistant/#`); used by every diagnostic read (`mqtt.sh sub`, `pool_status.sh`). A status check can therefore never move the pump.
The host clients (`mosquitto-clients`, installed 2026-10-06) read their credentials from `~/.config/mosquitto_sub` (poolread) and `~/.config/mosquitto_pub` (poolmqtt), so on the Pi `mosquitto_sub -t <topic> -C 1 -W 70` / `mosquitto_pub -t <topic> -m <payload>` need no `-u/-P` and nothing shows in `ps`. Both passwords are also in `~/.config/pool/secrets.env` (`MQTT_USER/MQTT_PW`, `MQTT_RO_USER/MQTT_RO_PW`, mode 600) — the fallback the scripts source when the host clients are missing, and the `EnvironmentFile` of `poolfast.service`. Never print those files or paste a password into a command or an answer; use `scripts/mqtt.sh` and `scripts/pool_status.sh` from the Mac. To let `poolread` see a new topic, add a `topic read <pattern>` line under `user poolread` in `aclfile` and `sudo docker restart mosquitto` (HA and the Atom reconnect within a minute). Changing a password: `mosquitto_passwd -b` via `docker run --rm -v ~/homeassistant/mosquitto/config:/mosquitto/config eclipse-mosquitto:2 …`, then update `secrets.env`, both option files, the HA MQTT integration and the Atom (`MqttPassword`) — only needed for `poolmqtt`.

Topics from the Atom/poller:
- `tele/aquarite/SENSOR` (60 s): `NeoPool.{Time, Temperature, Filtration{State,Speed,Mode}, Redox{Data,Setpoint}, pH{Data,Min,Max,State,Pump,FL1,Tank}, Hydrolysis{Data g/h, Percent, State, Low, Boost, Cover, FL1, Runtime}, Relay{State[],Acid}, Powerunit}`. `Filtration.Speed` is WRONG at media/alta (driver bug) — use FAST `relay_raw`.
- `tele/aquarite/FAST` (5 s, poller): `cell_current` (raw register units; ≈ 220 at full 22 g/h production — not mA), `pwm` (≈ 13–15 k at full output; the pwm/cell_current ratio rises when salt is low or the water is cold), `status{POL1,POL2,ON_TARGET,LOW,FL1,COVER,REDOX_EN…}, relay_raw (bit0 acid, bit1 pump, bits 8-10 speed 1/3/7 = baja/media/alta), acid, rail_2430v_mv, rail_12v_mv, gh, pct, demand, state (Pol1/Pol2/Flow/OFF…)`. Not published while a block is "suspect" → HA sensors fed by FAST have `expire_after 60` and go `unavailable`.
- `stat/aquarite/RESULT`: command answers (`NPRead` returns `Data` as a hex string or a list of hex strings when count > 1; flooded by the poller's own `NPRead 0x0100`/`0x0020`). `stat/aquarite/WATCHDOG` (Rule1), `tele/aquarite/PHCFG` (retained acid-relay config).

Commands to the Atom (`cmnd/aquarite/<Command>`; chain with `cmnd/aquarite/Backlog`, ≤ 30 commands, `Delay` unit 0.1 s):
- `NPRead <addr>[,<count≤19>]`, `NPWrite <addr> <val>`, `NPWriteL <addr> <v1> <v2> …` (32-bit pairs LSB-first), `NPBit <addr> <bit> <0|1>`, `NPExec`, `NPSave`, `NPEscape`, `NPTime 0` (sync controller clock from Atom), `NPRedox <mV>`, `NPHydrolysis <g/h|%>`, `NPPHRes 2`, `NPFiltrationMode 0|1|3` (Manual/Auto/Smart — never Smart), `NPFiltrationSpeed 1|2|3` (writes DEFAULT bits of 0x050F + EXEC; only visibly acts in Manual), `NPFiltration 0|1` (**forces Manual** — only used deliberately to start an override: `NPFiltrationSpeed s;Delay 50;NPFiltration 1`).
- Back to Auto: `NPFiltrationSpeed 2;NPFiltrationMode 1` (restores DEFAULT=media first so the conf word matches the plan).
- Tasmota: `Time`, `Status 7` (NTP/TZ), `Status 11`, `Rule1`, `Rule2`, `Event hb=1` (HA heartbeat).

HA command channels (automations in `pool_alkalinity.yaml`; the only way to drive HA without an API token):
- `pool/cmd/input_number/<pool_*>` payload number; `pool/cmd/input_boolean/<pool_*>` `on|off`; `pool/cmd/input_select/<pool_*>` payload = option text (e.g. `pool_plan_modo` → `Automático`); `pool/cmd/script/<pool_*>` runs a script (no variables); `pool/cmd/alk_baseline_ppm <ppm>` (re-baseline the TA model from a drop test); `pool/cmd/bicarb_kg <kg>` (log a bicarbonate addition); `pool/cmd/acid_type <option>`.
- HA `number.pool_target_redox` (controller redox setpoint) publishes `NPRedox x;NPSave` when set from HA — do NOT set it while the controller is in Manual; use `scripts/mqtt.sh pub cmnd/aquarite/NPRedox 750` (no save; the 17:30 write persists it).

## NeoPool Modbus registers worth knowing
`0x0101` cell current, `0x0102` pH×100, `0x0107` pH status, `0x010D` status word, `0x010E` relay state (bit0 acid, bit1 filtration, bits 8-10 speed), `0x010F` PWM, `0x0022/0x0023` 24-30 V and 12 V rails, `0x0289` manual ctrl, `0x0297` ESC, `0x02F0` save, `0x02F5` exec, `0x0408/0x0409` controller time (unix epoch low/high), `0x040A` acid relay number (=1), `0x0411` FILT_MODE (0 Manual, 1 Auto, 3 Smart, 13 Backwash), `0x0413` manual relay state, `0x041B` Smart %, `0x042A/0x042B` acid pulse on/off, `0x0430–0x0433` pH relay config (`0x0431` MAX_TIME minutes cumulative, `0x0432` RELAY_MODE 2 = alarm+stop, first write needs `NPExec`), timers `0x0434` (T1) / `0x0443` (T2) / `0x0452` (T3): 15 regs each (+0 ENABLE 0 off / 1 window / 3 always-on, +1..2 ON seconds LSB-first, +5..6 PERIOD 86400, +7..8 INTERVAL seconds, +11 FUNCTION 1), `0x050F` filtration conf (bits 0-3 TYPE=1 Hayward VS, 4-6 DEFAULT speed, 7-9 INT1, 10-12 INT2, 13-15 INT3; 0 baja / 1 media; e.g. `0x0491` = T1 media, T2 media, T3 baja; `0x0011` = all baja with DEFAULT media).
Semantics proven 2026-09-22: writing an active timer + `NPExec` does not open the relay (≈10 s cell pause); ALWAYS_ON uses the DEFAULT speed; windows use the per-interval speed; `NPWrite 0x050F` overwrites the DEFAULT bits an override set with `NPFiltrationSpeed` (the package re-sends the speed).

## Recorder recipes (python3 on the Pi, see `scripts/recorder.py`)
- Latest state: join `states` ↔ `states_meta` on `metadata_id`, order by `last_updated_ts desc limit 1`; attributes via `state_attributes.shared_attrs` (JSON; `sensor.pool_plan_hoy` has `historial`, `strip`, `N`, `H_filt`, `verificado`).
- Timestamps are UTC epochs. To filter by local time: `strftime('%s', datetime('2026-10-01 08:00:00','utc'))`. To print: `datetime(ts,'unixepoch','localtime')`.
- Excluded from the recorder (read live instead): `sensor.pool_timer*_raw`, `sensor.pool_filtration_conf_raw`, `sensor.pool_excedente_virtual`, `sensor.pool_neopool_clock_lag`, `sensor.pool_neopool_clock_lag_live`, `sensor.pool_plan_proximo_evento`, `sensor.pool_tesla_carga_kwh`, `sensor.piscina_aquarite_plus_neopool_time`, some automations.
- Rows exist only on state change: a flat value (e.g. pH 7.60 for an hour) has no rows — absence ≠ missing data.
- Automation `last_triggered` is in attributes of `automation.*`.
- **Events table** (who did what, when — the best evidence for races and owner actions): `events e join event_types t on e.event_type_id=t.event_type_id left join event_data d on e.data_id=d.data_id`; filter `t.event_type in ('call_service','automation_triggered')` and a time window; `d.shared_data` holds the JSON (service, entity_id, automation name). Example: list every `mqtt.publish` / `number.set_value` / `input_boolean.turn_*` between two times to reconstruct a sequence second by second.
- Credentials live in `~/scratch/atom-pool/AUTH.md` and inside the scripts; do not echo them.

## Poller JSONL analysis
Each line: `{"ts": "...+02:00", "cell_current", "pwm", "status_raw", "status": {...}, "relay_raw", "acid", "rail_2430v_mv", "rail_12v_mv", "gh", "pct", "demand", "state"}` (some lines lack rails when the block was suspect — use `.get`). Integrate `dt` between consecutive samples (< 60 s) to get hours by speed, chlorine grams (`gh × dt`), no-flow time with relay on (`status.FL1 == False`). `scripts/poller_report.py` does the daily table; copy its remote snippet for ad-hoc windows (e.g. transitions between two times).

## Deploy runbook (every HA file change)
1. Edit in `~/scratch/atom-pool/`; validate: `ruby -ryaml -e 'YAML.load_file("packages_pool_scheduler.yaml")'`; `grep -o "^    id: [a-z0-9_]*" packages_pool_scheduler.yaml | sort | uniq -d` must be empty; count aliases if you added automations.
2. Confirm the Pi runs what you think: `md5sum` of the deployed file vs the pre-edit copy (keep `/tmp/*.pre*.yaml` snapshots; `scp` the Pi file and `diff`).
3. Choose the window: no override active (`input_boolean.pool_override_activo` off) or accept that `pool_ha_start` ends it; avoid 09:50 and 17:24–17:35 (write windows).
4. `scp` to `/tmp` on the Pi; `STAMP=$(date +%Y%m%d-%H%M%S); sudo cp -p <dst> <dst>.bak.$STAMP; sudo install -o root -g root -m 644 /tmp/<file> <dst>`; `cd ~/homeassistant && sudo docker compose restart homeassistant`.
5. After ~4 min: `docker logs --since` filtered for `error|warning` minus the usual noise (`huawei_solar`, `cast`, `bluetooth`, `tesla_ble`, `value_json.NeoPool`, `invalid authentication`); check new entities exist (recorder), `binary_sensor.pool_plan_verificado` on after the 3-min readback, link ok, FAST ok, Pi memory.
6. Append a dated entry to `SCHEDULER-DEPLOY.md` §B (what, why, md5, backup stamp, verification) and update memory. Rollback = `sudo install` the `.bak.$STAMP` file back and restart.
7. New churny sensors (updating every minute) go into the recorder `exclude` list in `configuration.yaml` (edit on the Pi with backup).
