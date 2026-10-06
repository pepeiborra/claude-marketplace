#!/bin/sh
# One-shot status report of the pool system (read-only). Prints: live NeoPool telemetry, poller FAST,
# key HA entities, today's plan + historial, chemistry model, alarms and recent HA log problems.
DIR=$(cd "$(dirname "$0")" && pwd)
# Credentials stay on the Pi: host mosquitto_sub reads ~/.config/mosquitto_sub (user poolread, read-only);
# fallback to the container client with ~/.config/pool/secrets.env if mosquitto-clients is not installed.
PRE='if command -v mosquitto_sub >/dev/null 2>&1; then msub() { mosquitto_sub "$@"; }; else . ~/.config/pool/secrets.env; msub() { sudo docker exec mosquitto mosquitto_sub -h localhost -u "$MQTT_RO_USER" -P "$MQTT_RO_PW" "$@"; }; fi;'
"$DIR/pi.sh" "$PRE date; echo '=== NeoPool (tele SENSOR, 60 s) ==='; msub -t tele/aquarite/SENSOR -C 1 -W 70 | python3 -c '
import sys,json
d=json.load(sys.stdin); n=d[\"NeoPool\"]
print(\"HA/Atom time\", d[\"Time\"], \"| NeoPool time\", n.get(\"Time\"))
print(\"Filtration\", n.get(\"Filtration\"), \"| Temp\", n.get(\"Temperature\"))
print(\"Redox\", n.get(\"Redox\"), \"| pH\", n.get(\"pH\"))
h=n.get(\"Hydrolysis\",{}); print(\"Hydrolysis\", {k:h.get(k) for k in (\"Data\",\"Percent\",\"State\",\"Low\",\"Boost\",\"Cover\",\"FL1\")})
print(\"Relay\", n.get(\"Relay\"))
' 2>&1; echo '=== Poller FAST (5 s) ==='; msub -t tele/aquarite/FAST -C 1 -W 15 | cut -c1-330; echo; echo '=== HA entities ==='; python3 - <<'PY'
import sqlite3, json
c=sqlite3.connect('file:/home/pi/homeassistant/homeassistant/config/home-assistant_v2.db?mode=ro', uri=True)
def last(e):
    return c.execute('''select s.state, datetime(s.last_updated_ts,'unixepoch','localtime'), a.shared_attrs from states s
      join states_meta m on s.metadata_id=m.metadata_id left join state_attributes a on a.attributes_id=s.attributes_id
      where m.entity_id=? order by s.last_updated_ts desc limit 1''',(e,)).fetchone()
groups = {
 'bomba/plan': ['sensor.pool_filtration_mode','sensor.pool_speed_real','binary_sensor.pool_pump_relay','binary_sensor.pool_en_horario_programado',
   'input_select.pool_plan_modo','input_boolean.pool_mantenimiento','input_boolean.pool_modo_cubierta','input_boolean.pool_sched_suspendido',
   'input_boolean.pool_override_activo','input_select.pool_override_tipo','binary_sensor.pool_plan_verificado','sensor.pool_h_filt_objetivo',
   'sensor.pool_horas_filtracion_desde_10','input_number.pool_chlor_hours','counter.pool_overrides_hoy','counter.pool_np_writes_hoy','counter.pool_np_saves_hoy'],
 'quimica': ['sensor.pool_ph_value','sensor.pool_redox','input_number.pool_redox_objetivo','number.pool_target_redox','input_number.pool_redox_operativa_max',
   'sensor.pool_orp_fraccion_ok','sensor.pool_alkalinity_estimated','input_number.pool_alk_baseline','sensor.pool_acid_dosed_24h',
   'input_select.pool_acid_type','sensor.pool_lsi','input_number.pool_calcium_hardness','input_number.pool_cya','sensor.pool_ph_alarm','sensor.pool_ph_pump_mode'],
 'salud/alarmas': ['sensor.pool_neopool_link','binary_sensor.pool_fast_ok','binary_sensor.pool_ph_not_responding','binary_sensor.pool_ph_pump_timeout',
   'binary_sensor.pool_orp_bajo_dia','binary_sensor.pool_flow_alarm','binary_sensor.pool_cell_maxed','binary_sensor.pool_cell_declining',
   'input_number.pool_neopool_clock_lag_s','sensor.pool_atom_uptime','input_number.pool_solar_gate_level','sensor.pool_excedente_5min'],
}
for g, ents in groups.items():
    print('--', g)
    for e in ents:
        r = last(e); print(f'  {e:48s}', (r[0][:40], r[1]) if r else None)
r = last('sensor.pool_plan_hoy'); a = json.loads(r[2] or '{}') if r else {}
print('=== Plan de hoy ===', r[0] if r else None, '| verificado', a.get('verificado'), '| strip', a.get('strip'))
for l in a.get('historial', [])[:10]: print('   ', l)
r = last('sensor.pool_plan_manana'); print('=== Plan de mañana ===', r[0] if r else None)
PY
echo '=== HA log (errores/avisos pool, 12 h) ==='; sudo docker logs homeassistant --since 12h 2>&1 | grep -i -E 'error|warning' | grep -i -E 'pool|piscina|neopool' | grep -v -E 'value_json.NeoPool|Already running' | tail -8 | cut -c1-220; echo '=== Pi ==='; free -m | sed -n 2,3p; uptime; systemctl show poolfast -p TasksCurrent --value | sed 's/^/poolfast tasks: /'"
