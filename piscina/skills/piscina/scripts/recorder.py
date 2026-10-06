#!/usr/bin/env python3
"""Read-only queries against the HA recorder on the Pi (sqlite, mode=ro; NEVER immutable=1).
Runs locally and ships itself over ssh. Usage:
  recorder.py last  entity_id [entity_id ...]            latest state (+ last_updated local time)
  recorder.py attrs entity_id                            latest state + attributes JSON (e.g. sensor.pool_plan_hoy historial)
  recorder.py hist  entity_id "YYYY-MM-DD HH:MM" [end]   state changes since local time (max 400 rows)
  recorder.py hourly entity_id "YYYY-MM-DD HH:MM" [end]  hourly avg/min/max of a numeric sensor
Notes: timestamps in the DB are UTC epochs; this script converts local times correctly.
Entities excluded from the recorder (pool_timer*_raw, pool_excedente_virtual, pool_neopool_clock_lag*,
piscina_aquarite_plus_neopool_time ...) return None here -> read them live via MQTT instead.
"""
import sys, subprocess, json, shlex
REMOTE = r'''
import sqlite3, sys, json
args = json.loads(sys.argv[1])
c = sqlite3.connect("file:/home/pi/homeassistant/homeassistant/config/home-assistant_v2.db?mode=ro", uri=True)
def ep(s): return c.execute("select strftime('%s', datetime(?, 'utc'))", (s,)).fetchone()[0]
def last(e):
    return c.execute("""select s.state, datetime(s.last_updated_ts,'unixepoch','localtime'), a.shared_attrs
        from states s join states_meta m on s.metadata_id=m.metadata_id left join state_attributes a on a.attributes_id=s.attributes_id
        where m.entity_id=? order by s.last_updated_ts desc limit 1""", (e,)).fetchone()
cmd = args[0]
if cmd == "last":
    for e in args[1:]:
        r = last(e); print(f"{e:60s}", (r[0], r[1]) if r else None)
elif cmd == "attrs":
    r = last(args[1]); print(args[1], r[0] if r else None, r[1] if r else "")
    if r and r[2]:
        a = json.loads(r[2])
        for k, v in a.items():
            if k == "historial":
                print("historial:"); [print("   ", l) for l in v]
            else: print(f"  {k}: {v}")
elif cmd in ("hist", "hourly"):
    e = args[1]; t0 = ep(args[2]); t1 = ep(args[3]) if len(args) > 3 else "9999999999"
    if cmd == "hist":
        rows = c.execute("""select s.state, datetime(s.last_updated_ts,'unixepoch','localtime') from states s join states_meta m
            on s.metadata_id=m.metadata_id where m.entity_id=? and s.last_updated_ts between ? and ? and s.state not in ('unavailable','unknown')
            order by s.last_updated_ts limit 400""", (e, t0, t1)).fetchall()
        for st, ts in rows: print(ts, st)
    else:
        rows = c.execute("""select strftime('%m-%d %H', s.last_updated_ts,'unixepoch','localtime') h, round(avg(cast(s.state as real)),2),
            min(cast(s.state as real)), max(cast(s.state as real)), count(*) from states s join states_meta m on s.metadata_id=m.metadata_id
            where m.entity_id=? and s.last_updated_ts between ? and ? and s.state not in ('unavailable','unknown') group by h order by h""", (e, t0, t1)).fetchall()
        for r in rows: print(r)
'''
if len(sys.argv) < 3: print(__doc__); sys.exit(1)
payload = json.dumps(sys.argv[1:])
cmd = f"python3 -c {shlex.quote(REMOTE)} {shlex.quote(payload)}"
sys.exit(subprocess.call(["ssh", "pi", cmd]))
