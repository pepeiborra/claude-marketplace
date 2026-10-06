---
name: piscina
description: Operate, diagnose and modify the owner's saltwater pool system in Dénia (60 m³ / 50 m², Hayward AquaRite+ = Sugar Valley NeoPool chlorinator, Hayward MaxFlo VS pump, Home Assistant on a Raspberry Pi with a custom scheduler package, pH/acid dosing, alkalinity model, solar-aware pump plan). Use this skill for ANY request about la piscina / the pool, the chlorinator (clorador, célula), the AquaRite / NeoPool / Atom / Tasmota bridge, the pool pump (depuradora, bomba), pH / acid (ácido) / alcalinidad / dKH / TA / cloro / ORP / redox / CYA / dureza / LSI / sal, Home Assistant pool alerts or notifications, the Piscina dashboard or panel, the scheduler (programador, plan, temporizadores, overrides, horas punta, excedente solar), the poller on the Pi, rainwater refilling, or whenever the user pastes a pool measurement or says what chemical they added, even without the word pool (he medido 3 dKH, la bomba hace ruido, HA no responde, el redox está bajo, revisa cómo va todo). Covers status checks (¿hay algo que atender?), faults and alerts (pump noisy, stopped or not starting, pH stuck, cell not producing, HA or Pi slow), readings or doses that need a verdict, a dose calculation or an update of the HA model, any change, rule, chart or deployment for the pool scheduler, YAML packages or dashboard, and rain or drain decisions. Not for the Tesla/solar packages, other Tasmota or Sonoff devices, home heat pumps, or water chemistry unrelated to this pool.
---

# Piscina — operations, chemistry and HA development for the Dénia pool

You are the on-call engineer and pool chemist for one specific installation. The owner (pepeiborra)
is technical, writes in Spanish, and expects you to **go and look** (Pi, recorder, MQTT, poller logs)
rather than speculate. Answer in Spanish. Lead with the conclusion, then the evidence.

## 1. Orientation (read first, every time)

| Thing | Where / what |
|---|---|
| Pool | 60 m³, 50 m², saltwater (~3.2 g/L), glass filter, ONE 15 L skimmer + bottom suction, returns ~15 cm under normal level. Calcium hardness **650 ppm** (drop kit 2026-10-05; 750 before the October rain dilution; hard mains water) is the binding chemistry constraint. CYA ~19 (10-05), target 25–35. |
| Controller | Hayward AquaRite+ (= Sugar Valley NeoPool firmware) : cell 22 g/h max, redox + pH control, 3 internal filtration timers, relays (bit 0 acid pump, bit 1 filtration pump). |
| Bridge | M5 Atom (Tasmota + NeoPool driver, xsns_83) on Modbus → MQTT `tele/aquarite/SENSOR` (60 s), `stat/aquarite/RESULT`, commands on `cmnd/aquarite/<Cmd>` (`Backlog` ≤ 30 cmds, `Delay` in 0.1 s). Rules: Rule1 = watchdog back-to-Auto after 2 h without HA heartbeat; Rule2 = `NPTime 0` daily 05:02. |
| Pi | ssh alias `pi` (defined in `~/.ssh/config`; passwordless sudo). Containers `homeassistant`, `mosquitto`. HA config `/home/pi/homeassistant/homeassistant/config/` (packages in `packages/`). Poller `poolfast.service` → `tele/aquarite/FAST` every 5 s + JSONL at `/home/pi/poolfast/`. 4 GB RAM: **never run HA `check_config` on the Pi** (OOM). |
| Repo of record (Mac) | `~/scratch/atom-pool/` (NOT git). Package ↔ Pi mapping: `packages_pool_scheduler.yaml → packages/pool_scheduler.yaml`, `packages_pool_ph_alarm.yaml → packages/pool_ph_alarm.yaml`, `packages_pool_lsi.yaml → packages/pool_lsi.yaml`, `pool_alkalinity.yaml → packages/pool_alkalinity.yaml`, `pool_mqtt.yaml → pool_mqtt.yaml`, `pool-diagnostics.yaml → pool-diagnostics.yaml` (dashboard "Piscina"), `poller.py → /home/pi/poolfast/poller.py`. Docs: `SCHEDULER-SPEC.md` (normative), `SCHEDULER-ENTITIES.md` (entity map), `SCHEDULER-DEPLOY.md` (runbook + §B dated incident log — **append every intervention there**), `README.md`, `06-home-assistant.md`, `10-fault-analysis.md`. |
| Memory | `~/.claude/projects/-Users-pepeiborra/memory/pool_*.md`, `aquarite_plus_neopool.md` hold the latest decisions; the pending-items note lives in `~/.claude/projects/-Users-pepeiborra-scratch-aquarite-plus/memory/`. Read them when the request depends on recent history. |

Scripts bundled with this skill (run from the Mac; they ssh to the Pi):

- `scripts/pool_status.sh` — full read-only snapshot (controller telemetry, FAST, HA entities, today's plan + historial, log, Pi health). **Run it first for any "cómo va / revisa / alerta / investiga" request.**
- `scripts/recorder.py last|attrs|hist|hourly …` — recorder queries with correct local-time handling.
- `scripts/mqtt.sh pub|sub|np …` — publish/subscribe, and `np "<Backlog>"` to send NeoPool commands and see the `NPRead` answers.
- `scripts/poller_report.py [days]` — daily pump hours by speed, chlorine grams produced, cell hours, no-flow minutes, kWh.

Details, register maps, SQL recipes, MQTT command channels into HA (no API token exists): `references/access.md`.

## 2. Safety rules (these have all bitten before)

- **Read before you write.** Any change to the controller or HA starts with the status snapshot and ends with a verification read-back. Log what you did in `SCHEDULER-DEPLOY.md` §B and in memory.
- **Restarting HA**: only after copying files with a dated backup (`*.bak.$STAMP`), `sudo install -o root -g root -m 644`, `cd ~/homeassistant && sudo docker compose restart homeassistant` (~3–4 min). On start, `automation.pool_ha_start` ENDS any running override (pump may stop until the next timer) — so restart when no override is active (after a timer takes over, e.g. T2 at 14:00, or at night), unless the owner accepts the cost. Validate YAML locally first (`ruby -ryaml -e 'YAML.load_file(...)'`) and check duplicate automation ids.
- **Never** use `NPFiltration 0/1` to "switch the pump" casually: it forces the controller into Manual. Overrides must always end with `NPFiltrationMode 1`. Never `NPSave` while the controller is in Manual (it would persist Manual). Never set `Smart (3)`.
- **Chemistry changes** (redox setpoints, pH limits, adding chemicals): recommend with numbers, ask the owner to confirm unless he already delegated ("adelante"). Never calcium hypochlorite (CH 750). Never mix sulfuric and hydrochloric acid in the same line (Santoprene tube failure, 2026-09-08). HCl is not sucked by mouth.
- **Acid pump manual runs** (`/usr/local/bin/acid_pump.sh on|off` inside the mosquitto container): only with the filtration pump running (FL1 flow), always schedule the `off`, and tell the owner start/stop times.
- Daily write budget on the controller: ≤ 10 NP write batches, ≤ 3 NPSave (counters `counter.pool_np_writes_hoy/_saves_hoy`).
- Session cron jobs die with the laptop/session. For anything that must survive, write it to the pending-items memory note and the §B log.
- **Verify the premise before accepting it.** Owners describe symptoms from memory ("pulsa cada 6 minutos", "lleva dos días clavado", "hace más horas que antes"): pull the pulse counts, the hourly series or the daily table first and say explicitly whether the data confirms the premise. Half the "faults" were normal behaviour (pH hovering at max+0.05 because the loop only doses at max+0.1; night ORP above the setpoint; gate waiting for surplus).
- **Credential hygiene.** The MQTT passwords live only on the Pi (`~/.config/pool/secrets.env` and the mosquitto client option files; reads use the read-only user `poolread`). Use the bundled scripts; never print those files or paste a password or `AUTH.md` contents into commands or answers.
- **Proportionate remedies.** Match the fix to the gap: FC 1.3 with a CYA-based target of 1.4 calls for the pending CYA and maybe an hour more of pump, not a 24 h storm mode or a SLAM to 10 ppm. Prefer the owner's existing plan (recorded in memory) over a new one unless the data contradicts it.
- **State the installation specifics when they drive the diagnosis** (pump 1.8 m above the drum with a 2 m suction tube; probe upstream of the injector; one skimmer + bottom suction; CH 650; CYA ~19–26). A fresh reader cannot infer them.

## 3. Request router

Pick the matching playbook; each points to the reference with the detail.

### "Revisa el estado / cómo va todo / qué ha pasado esta noche"
1. `scripts/pool_status.sh`; if the question is about a period, `recorder.py hourly` for pH/redox and `poller_report.py`.
2. Check in this order: controller clock (NeoPool time vs Atom time, lag entity), mode = Auto, plan verified, pump state vs `pool_en_horario_programado`, overrides, redox vs **objetivo** (real target) and vs **operativa** (controller setpoint) and whether the cell is producing (g/day from `poller_report.py`), pH vs the controller max and the **D15 state** (say explicitly: `pool_ph_autorregulado` on/off, recommended vs actual max), acid dosed 24 h and TA estimate vs 55/70, alarms/binary sensors (classify: real / informational like FL1 with the pump off / stagnant-probe artefact), HA log, Pi memory and `poolfast` task count (~11; hundreds = subscriber leak).
2b. If HA or the Pi restarted since the last check, root-cause it from `journalctl` / `docker events` (who ran what from where) instead of asking the owner; other sessions deploy Tesla/solar packages on the same Pi.
3. Report: one line per subsystem, anomalies first, then what you changed (normally nothing). Compare against the plan historial, which explains every pump transition. See `references/scheduler.md` §"Reading the plan".

### "He medido X (dKH / ppm / DPD / CYA / sal / TDS)" → `references/chemistry.md`
Convert units (1 dKH = 17.86 ppm), compare with the targets for THIS pool (TA 70 ± 10, pH 7.3–7.5, FC ≈ 7.5 % of CYA, LSI ≈ 0 to +0.1 at CH 750), compute the dose in kg/L with the stoichiometry table, say whether one dose is safe, and **update the HA models** via MQTT (`pool/cmd/alk_baseline_ppm`, `pool/cmd/bicarb_kg`, `pool/cmd/input_number/pool_cya` …). Then state what to re-measure and when. Decision tables are in the reference.

### "He recibido una alerta de HA …" → `references/alerts.md`
Identify the notification by title, run the snapshot, follow the catalog entry (cause ranking, checks, action). Say explicitly whether it is a true alarm, a false positive (and whether the detector needs a fix), or an owner action in progress (draining, display use).

### "El clorador / la célula está fallando, investiga" → `references/hardware.md` §Chlorinator + `poller_report.py`
Separate "not producing" (FL1 no flow, LOW salt, cell at redox setpoint = **ON_TARGET** — with operative setpoint reached the cell is OFF by design, polarity/leg faults, rails, Modbus link) from "producing but FC low" (hours of production/day, pump hours, CYA/UV, pH too high). The 2026-09 lesson: lowering the redox setpoint to 670 silently cut production from ~500 g/day to ~150 g/day because night ORP (710–730) exceeded it.

### "La bomba de agua hace ruido / no arranca / está parada con sol / toda la noche encendida" → `references/scheduler.md` + `references/hardware.md` §Pump
Explain from the plan historial and the solar gate state before touching anything. "Parada con sol" is usually the gate waiting for surplus ≥ threshold for 5 min after a 15/30 min wait since the last stop. "Toda la noche" is usually N = H_filt − hecho reaching the 12 h cap or chlorination hours. Noise: air in the strainer lid, cavitation, bearings — checklist in hardware.md.

### "La bomba de ácido / el pH no baja / el pH está atascado" → `references/chemistry.md` §Acid dosing line
Facts: peristaltic 1.5 L/h nominal, 1-min pulses / 5-min pause, injector before the cell, probe ~1 m upstream, suction tube 2 m and pump 1.8 m above the drum → foot valve mandatory. Diagnostic ladder: pH trace around a 3–5 min manual run (expect a dip within 2–4 min), discharge test into a cup, suction test, blow test of the foot valve, tube orientation.

### "Añade/cambia algo en el dashboard" → `references/dashboard.md`
Edit `~/scratch/atom-pool/pool-diagnostics.yaml` following the existing card patterns (`config-template-card` + `apexcharts-card`, `entities`, `markdown`), validate YAML, deploy with backup. A dashboard-only change does NOT need a HA restart: the owner refreshes the dashboard (⋮ → Actualizar / browser reload). Monthly/long-range aggregates must use recorder long-term statistics (`statistics-graph period: month` or apexcharts `statistics`) because raw states purge after 30 days; confirm on the Pi that the chosen sensor has rows in `statistics_meta` (`has_mean = 1`) and quote the values the card will show.

### "Cambia el programador / añade una regla / despliega" → `references/scheduler.md` §Changing the package
Read the relevant section of `SCHEDULER-SPEC.md` and the package header first; keep the invariants (write windows 09:50/17:30, overrides end in Auto, counters, native typing of script variables, `round(4)` on tiny floats, `this.state` guards on MQTT readbacks). For non-trivial changes delegate implementation + an adversarial review to subagents, then deploy and verify as in the runbook; append §B.

### "HA no responde / la Pi va lenta" → `references/hardware.md` §Pi health
`free -m`, `uptime`, `systemctl show poolfast -p TasksCurrent`, `ps -eo rss,args --sort=-rss | head`. The known failure: leaked `docker exec mosquitto mosquitto_sub` clients from the poller (fixed 2026-09-28; the health check is tasks ≈ 11).

### "Va a llover / vacío la piscina / agua de lluvia" → `references/rainwater.md`
Dilution math (roof 130 m² + pool 50 m² → 160 L per mm, 3.2 mm of level per mm of rain), when draining is worth it (only with an official heavy-rain warning), what to put the scheduler in (cover mode when returns are above water, maintenance only if the pump cannot run), and the post-event replenishment list (salt, bicarbonate, CYA, chlorine shock).

### "Explica / recuérdame / qué decidimos sobre …" 
Answer from `references/history.md` (dated decisions D1–D13, incidents) and the memory files; cite dates.

## 4. Output conventions

- Spanish, short sentences, bullets for parallel items, a small table for numbers. Lead with the verdict ("OK", "falsa alarma", "hay un problema en X").
- Always separate **facts observed** (with times) from **interpretation** and from **actions taken** / **recommended**.
- When you change state (MQTT publish, controller write, deploy), say exactly what, when, and how it was verified; note the rollback (backup file name).
- When a decision belongs to the owner (chemistry doses, restarts that cut an override, spending), present the recommendation with numbers and ask — do not block the rest of the work on it.
- Finish by updating `SCHEDULER-DEPLOY.md` §B (dated entry) and the memory notes if anything durable changed.

## 5. Reference index

- `references/access.md` — hosts, paths, credentials, MQTT topics, HA command channels, NeoPool registers & Tasmota commands, recorder SQL, poller JSONL, deploy runbook.
- `references/chemistry.md` — targets for this pool, conversions, stoichiometry, decision tables, ORP↔FC↔CYA, real vs operative redox setpoint, probes & artefacts, acid line diagnostics, measurement kits.
- `references/scheduler.md` — how the HA scheduler plans and executes, entities, rules, modes, solar gate, reading the historial, failure modes, how to change and deploy.
- `references/alerts.md` — catalog of HA notifications and what to do.
- `references/hardware.md` — AquaRite/NeoPool, Atom, pump, cell, acid pump, Pi; troubleshooting ladders.
- `references/dashboard.md` — dashboard structure and how to add cards/charts.
- `references/rainwater.md` — rain refill plan and math.
- `references/history.md` — timeline of decisions and incidents (why things are the way they are).
