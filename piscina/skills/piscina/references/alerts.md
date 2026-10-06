# HA notification catalog (title → meaning → what to check → action)

All go to `notify.mobile_app_pephone_pro_17` via `script.pool_notificar` (some persistent in HA). Start every alert triage with `scripts/pool_status.sh` and the `historial` of `sensor.pool_plan_hoy`. Classify as: real / false positive (then fix the detector) / owner action (draining, display) / already self-healed.

## Pump and plan
- **"Piscina: la bomba no arranca"** (`binary_sensor.pool_no_arranca` 45 min): a plan block is active but the relay is open. Check: controller mode (`sensor.pool_filtration_mode` must be 1), **controller clock vs Atom** (`NeoPool.Time` in SENSOR; lag > 300 s → `NPTime 0`), `pool_plan_verificado` and the raw timer readbacks (`mqtt.sh np "NPRead 0x0434,9; NPRead 0x0443,9; NPRead 0x0452,9; NPRead 0x050F,1"`: ENABLE words and ON/INTERVAL), maintenance/suspended flags, FL1/Backwash on the display, breaker. The message now includes the clock lag.
- **"Piscina: bomba 3 h fuera del plan"** (R5c): pump running with no plan block/override/timer window. Causes: display Manual, owner draining, stale legacy timer. Actions offered: "Volver a Auto" / "Es mantenimiento". If a controller timer explains it, the detector is wrong → check `pool_timer*_raw` live.
- **"Piscina: bomba en marcha SIN CAUDAL 1 h"** (R5b): FL1 open with relay closed 1 h → the package stops the pump and sets `pool_sched_suspendido`. Causes: pumping to waste (draining), air lock, closed valve, empty strainer, low water. Owner clears with "Reanudar"; re-prime first. `automation "sin caudal 10 min: subir a media si Manual"` is the softer precursor.
- **"Piscina: controlador en Manual y bomba parada"** (watchdog 20 min): Manual without an override. Options: "Activar mantenimiento" / "Volver a Auto ya"; otherwise auto-returns to Auto in 2 h.
- **"Piscina: plan de día/noche NO verificado"**: readback ≠ plan after 3 retries. Check link (`sensor.pool_neopool_link`), Modbus flood, write counters ("escritura BLOQUEADA (tope 10/día)", "NPSave omitido (tope 3/día)"), controller in Backwash. Re-run `script.pool_replanificar_ahora` (`pool/cmd/script/…`) when clear.
- **"Piscina: déficit de filtración"**: H_filt − hecho − 12 > 2 h without cover. Usually a cloudy day without overrides plus a short night; informational unless repeated.
- **"Piscina: override no confirmado"** / **"el controlador no vuelve a Auto"** / **"Backwash en curso, no se vuelve a Auto"**: see mode on the display; Backwash (13) is never overridden — wait.
- **"Piscina: parada diferida por ácido"**: an override end waited 45 min for the acid interlock. Since 2026-09-29 this should only happen if acid pulses really never pause for 2 min; check `binary_sensor.pool_acid_relay_fast` history. If the pump was going to keep running under a timer anyway, it is harmless.
- **"Piscina: arranque ignorado (programador SUSPENDIDO / modo X)"**, **"marcha manual ignorada"**, **"tormenta ignorada / no aplicada"**, **"temporizadores OFF bloqueado (tope 10/día)"**: guard rails; explain and, if the budget is the blocker, wait for midnight reset.
- **"Piscina: escribiendo plan de reserva"**: no verified plan for 48 h → seasonal fallback written. Investigate link/clock/write failures.
- **"Piscina: mantenimiento activado"**, **"punta forzada activada/desactivada"**, **"baño intenso"** (offers "Marcha manual 2 h"): informational.

## Chlorination / redox
- **"Piscina: ORP bajo de día"** (redox < objetivo − 80 between 11–18 h for 2 h with the pump on) and **"Piscina: ORP SEVERO"** (< 600 mV 1 h): check production first — `poller_report.py` (cloro_g, h_cel), cell `pct/gh` in FAST, `LOW` salt flag, FL1, `ON_TARGET` with the operative setpoint, pump hours; then FC by DPD, CYA, pH. See hardware.md §Chlorinator.
- **"Piscina: ORP bajo con célula no saturada"**: deficit while the cell is not at 100 % → the controller is throttling (setpoint/`REDOX_EN`) — check the operative setpoint vs night plateau.
- **"Piscina: consigna operativa de redox A → B mV"** (17:24 rule result), **"… no aplicada"** (controller in Manual 40 min), **"… no confirmada"** (telemetry did not reflect NPRedox): see chemistry.md §Real vs operative.
- **"Pool: chlorinator cell may be declining"** (`pool_cell_health.yaml`): cell current/production trend; compare with `README.md` "cell decline detector" notes; a dirty cell was fixed by a swap in 08-2026.

## pH / acid
- **"⚠️ Bomba de pH parada — tiempo máximo excedido"** (controller code 3, RELAY_MODE 2, MAX_TIME 150 min cumulative): the controller gave up dosing. Causes: acid not arriving (foot valve, tube, empty drum), aeration, pH probe. Reset with the notification action "Reiniciar alarma (ESC)" (`script.pool_ph_alarm_reset` → `NPEscape`) only after fixing the cause. "✅ Bomba de pH operativa" clears it; "sigue parada" repeats every 12 h.
- **"⚠️ pH no responde al ácido / a la dosificación"**: ≥ 6 ppm TA destroyed in 24 h with pH never reaching max + 0.05 in 24 h → acid not reaching the pool. Run the acid-line ladder (chemistry.md). It was a true positive on 2026-09-26..29 (no foot valve) and a false positive on 10-02 before the 24-h-minimum condition was added.
- **"⚠️ Alcalinidad baja"** (model estimate < `pool_alk_warn` 55): verify with Salifert before dosing; the model drifts when acid does not actually arrive (over-counts) or after dilution.
- **"⚠️ LSI x — verdict"**: scaling/corrosive verdict from the live LSI; usually follows pH excursions; fix pH/TA cause.
- **"Alcalinidad recalibrada" / "Bicarbonato registrado" / "Ácido de la bomba actualizado"**: confirmations of MQTT commands.

## Infrastructure
- **"Piscina: sin contacto con el Hayward 2 h"** (`sensor.pool_neopool_link` expired) and **"Pool: Atom OFFLINE"**: Atom/WiFi/Modbus down. Check Atom uptime/RSSI (`sensor.pool_atom_uptime`, `pool_atom_rssi`), power rails, `mosquitto` container. The controller keeps running its saved plan autonomously.
- **"Piscina: poolfast.service sin datos 30 min"**: poller dead or leaking → `systemctl status poolfast`, tasks count, `journalctl -u poolfast`.
- **"Piscina: reloj del NeoPool desviado / corregido / NO corregido"**: clock drift; auto-resync; if NOT corrected, read `NeoPool.Time` vs Atom `Time`, check Rule2, resend `NPTime 0`.
- **"Piscina: Rule1 del Atom no está activa"** (Monday 08:00 check) / **"Piscina: fail-safe activado"** (Rule1 restored Auto): re-install rules from `tasmota_rules.txt` if needed.
- **"Pool: Atom lost power - suspect 12 V rail"**: historical power-module fault (repaired 08-2026); check rails in FAST (`rail_12v_mv` ≈ 13–15 V, `rail_2430v_mv` ≈ 28–34 V).
- **"🧪 Test mensual de la piscina"**: reminder to run the manual kit tests (FC, TA, CYA, salt).
