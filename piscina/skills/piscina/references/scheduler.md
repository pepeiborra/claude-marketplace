# The HA scheduler ("programador") — how it plans, how to read it, how to change it

Normative text: `~/scratch/atom-pool/SCHEDULER-SPEC.md` (sections cited below). Entity map: `SCHEDULER-ENTITIES.md`. Package: `packages_pool_scheduler.yaml` (≈ 5.5 k lines, 50 automations "Piscina · …", 21 scripts; the header comment block summarises every rule — read it before editing).

## Architecture B: "HA plans, the controller executes"
- The NeoPool stays in **Auto (mode 1)**. HA compiles the daily plan into the controller's three timers (T1 night, T2 day block, T3 extra/low) plus per-interval speeds in `0x050F`, writes them over MQTT, verifies by `NPRead` readback (`sensor.pool_timer{1,2,3}_raw`, `sensor.pool_filtration_conf_raw` → `binary_sensor.pool_plan_verificado`), retries, and persists with ONE `NPSave` per day.
- Writes: **A at 09:50** (T2 only, no save) and **B at 17:30** (T1 + T3 + conf + NPSave). A timer that is active at write time is deferred (retry every 15 min). `script.pool_replanificar_ahora` (field `forzar`) re-plans on demand; mode changes, cover toggle, maintenance off and HA start (if the last B is > 26 h old) call it.
- Overrides (solar, punta-baja, manual 2 h) run in **Manual** and always end with `script.pool_override_fin` → `script.pool_volver_auto` (`NPFiltrationSpeed 2;NPFiltrationMode 1`, verified 3×90 s). Safety nets: HA watchdog (Manual 20 min without override → back to Auto or ask), Atom Rule1 (2 h without heartbeat → Auto).
- "Pool day" = [08:00, 08:00) (D12). Reset at 07:55 (`automation.pool_reset_0755`): counters, ORP accumulators, `input_number.pool_cola_t1_hoy` (T1 tail past 08:00, discounted from "hecho").

## Daily quantities (R1/R2/D3)
- Water temperature T (median 24 h) → **H_filt = clamp(T/2, 6, 16) h at media** (+4 h bono bañistas, + `pool_ajuste_horas`). With **cover mode** (`input_boolean.pool_modo_cubierta`): H_media_equiv = clamp(T/2 × 0.6, 4, max) and the plan runs at **low**: H_filt = min(16, ceil₀.₂₅(H_media_equiv × 12.5/6.9)).
- "Hecho" = `sensor.pool_horas_filtracion_desde_10` (= hours at media since 08:00; with cover = hours running at any speed) minus `pool_cola_t1_hoy`.
- Day block T2 (laborable: llano 14–18, media; valle-24h days: centred on the solar envelope): L_day = ceil₀.₂₅(share × H_filt), share 0.35 (T ≥ 24), 0.20 (18–24), 0 (< 18, T2 off). With cover T2 is OFF (D13): the daytime remainder is covered only by solar overrides at low 08:00–17:20.
- Night at 17:30: N = clamp(H_filt − hecho, 4, 12) → T1 ends 08:00 (N ≤ 8: [08−N, 08); 8 < N ≤ 10: starts before midnight; > 10: 22:00 → 08:00+(N−10)). Extra chlorination hours L = max(0, H_chlor − H_filt) at low in T3 (08–10 after T1, or before T1 on valle days), remainder "pendiente" for the 18–22 punta-baja override (D2, only with live solar generation ≥ 240+150 W).
- R2 (17:25) adapts `input_number.pool_chlor_hours` from the daytime ORP deficit D (mean of max(0, objetivo − redox) over the 10:00–17:30 samples), f_maxed (fraction with the cell at ≥ 95 %) and the pre-dawn sample; since D14 it only ADDS hours when the operative redox setpoint is at its cap. R2b (17:24) adjusts the operative setpoint first (see chemistry.md).
- Calendar: 2.0TD tariff; valle 24 h on weekends and fixed national holidays (Jan 1, Jan 6, May 1, Aug 15, Oct 12, Nov 1, Dec 6, Dec 8, Dec 25); punta 10–14 and 18–22 on weekdays is a soft constraint.

## Solar gate and overrides (§3.6, "solar primero" D5)
- `sensor.pool_excedente_virtual` = max(0, meter + Tesla charging power) + pump power if running (the pump has priority over the car) → 5-min mean `sensor.pool_excedente_5min`; levels: 2 if ≥ `pool_umbral_gate2_w` (900 W) for 5 min, 1 if ≥ 540 W; down after 10 min below AND the hourly net budget (`sensor.pool_saldo_hora_wh`) exhausted. `input_number.pool_solar_gate_level`.
- Start (`automation.pool_override_inicio`): level ≥ 2 (≥ 1 with cover, then speed 1), window 08:00–13:30 weekdays / until T2−45 min on valle days / 08:00–17:20 with cover, never at 09:50, < 3 overrides per pool day, hecho < H_filt − 4, sky clear (`binary_sensor.tesla_despejado`) or surplus ≥ 1300 W, controller in Auto, and either a cold start (relay off, 15 min after a timer stop / 30 min after an override stop, priming budget OK) or a **take-over** from a running low-speed/ending timer (no relay cycle). Command `NPFiltrationSpeed s;Delay 50;NPFiltration 1`.
- Run: level 1 → speed 1, level 2 → speed 2 (never with cover); ≤ 4 speed changes/h; re-sends speed if the 09:50 conf write clobbers it.
- End (`automation.pool_override_fin`): level 0 for 10 min with ≥ 30 min run; net import (meter + car) < −1500 W for 5 min; T2 start (+30 s, relay stays closed); 14:00:30 on weekdays without a later T2 (not with cover); with cover: 18:00, or hecho ≥ H_filt − 4; cap 6 h (10 h with cover). Then `pool_override_fin` → acid interlock (only if the pump would actually stop; relay off ≥ 120 s since last acid pulse, `relevo_ok` skips it when a timer already covers) → Auto → accounting.
- "Mediodía nublado": 30 min without clear sky between 10 and 14 blocks further overrides until 14:00 (`input_boolean.pool_override_bloqueado_hoy`).
- Priming costs ≈ 700 W × 300 s per relay start; pump SP2310 1500 rpm 110 W / 2720 rpm 470 W / 3000 rpm 626 W + 130 W cell.

## Modes and switches the owner uses
- `input_select.pool_plan_modo`: **Automático** (normal), **Manual** (owner edits T1/T2/T3 numbers, written with 60 s debounce), **Pausado** (nothing written; A/B skipped "B omitida: plan en Pausado"). If the plan is stuck in Pausado, set Automático via `pool/cmd/input_select/pool_plan_modo` → triggers a replan.
- `input_boolean.pool_mantenimiento`: timers disabled (ENABLE 0) + Auto; no starts, no Manual watchdog; use while draining below the skimmer or working on the pump. Off → replan.
- `input_boolean.pool_modo_cubierta`: cover/low-speed mode (also handy when returns spray above a low water level: less aeration). Toggle → replan.
- `input_boolean.pool_modo_tormenta`: 24 h at media (T1 always-on), auto-off. `input_boolean.pool_sched_suspendido`: set by R5b (no flow 1 h) — owner must clear ("Reanudar").
- `input_boolean.pool_sched_modo_sombra`: shadow mode (plans logged, nothing written) — off since 2026-09-23.
- Owner-facing numbers: `pool_chlor_hours`, `pool_ajuste_horas`, `pool_filt_min_h/max_h`, `pool_redox_objetivo`, `pool_redox_operativa_max`, `pool_alk_*`, `pool_cya`, `pool_calcium_hardness`.

## Reading the plan (`sensor.pool_plan_hoy`)
State "T1 hh:mm-hh:mm M | T2 … | T3 … b" (M media, b baja, A alta). Attributes: `historial` (newest first — every write, override start/end with reason and hours, rule outputs, deferred writes, errors), `strip` (24 chars: · off, b/M/A planned speed, m solar-override window, p punta-baja), `N`, `H_filt`, `H_chlor`, `L`, `deficit`, `verificado`, `escrito_a/b`, `conf_hex`, `horas_filtracion`, `cola_t1_hoy`. `sensor.pool_plan_manana` = tomorrow's preview (17:35). `sensor.pool_plan_estado_deseado` = what HA thinks the pump should be doing now (OFF / Baja / Media / override / Pausa / Mantenimiento …). `binary_sensor.pool_fuera_de_horario` honours both the plan and the controller's own timer windows (2-min debounce).
To explain any pump transition: find the historial line around that time; cross-check `sensor.pool_speed_real` history (FAST bits) and the solar gate level.

## Known failure modes (and the fix that exists)
| Symptom | Cause seen | Handled by |
|---|---|---|
| Pump off with sun | gate waiting (surplus < 900 W for 5 min, 15/30 min since last stop, "mediodía nublado", 3 overrides used) | explain; nothing to fix |
| Pump all night at media | N hit 12 h because day achieved little, or chlor_hours inflated by R2 chasing an unreachable setpoint (pre-D14) | reset `pool_chlor_hours` to base; R2 now gated by operative cap |
| "la bomba no arranca" with timers verified | **controller clock wrong** (2026-10-01: −11 h 32 min after the 05:02 `NPTime 0`; controller believed 17:30, ran T2 until "18:00" = 05:32 real) | `automation.pool_reloj_resync` (|lag| > 300 s for 3 min → `NPTime 0`, verify, notify); manual fix `mqtt.sh pub cmnd/aquarite/NPTime 0`; compare `NeoPool.Time` with the Atom `Time` |
| Override end hangs, pump runs 60 min in Manual, "parada diferida por ácido" | acid interlock required 600 s without pulses while dosing pulses every 6 min (unreachable) | interlock now 120 s + `relevo_ok` (2026-09-29) |
| HA restart kills a running override | `pool_ha_start` ends overrides 2 min after start | restart when a timer covers the pump |
| Plan "verificado" false after maintenance/restart | timers disabled or readbacks not yet received | wait for the 3-min readback (`automation.pool_relectura_al_arrancar`, also every 6 h) |
| Write B says "NPSave diferido (controlador no está en Auto)" | override running at 17:30 | `automation.pool_save_diferido` saves when back in Auto — normal |
| Controller found in Manual/Smart | owner touched the display (power measurement 09-21), slider moved during an override | watchdog / Rule1; set Auto with `NPFiltrationSpeed 2;NPFiltrationMode 1` |
| Daytime "FL1 sin caudal" while draining | owner pumping to waste in Manual (flow switch on the return line) | set `pool_mantenimiento` on during drains so the watchdog does not interrupt |
| False R5c "fuera del plan" | legacy timer window not in HA plan | detector honours controller timers (fixed 09-23) |
| `pool_plan_verificado` off with `conf 0x0001 ≠ 0x0011` after a solar override | race: `pool_override_run` re-sent `NPFiltrationSpeed 1` ~80 s after `pool_volver_auto` because `pool_override_activo` is cleared last → DEFAULT speed bits overwritten in Auto | fixed 2026-10-05 (D-A): `pool_override_run` requires controller mode 0 and both fin/volver_auto scripts idle; `modo → 0` trigger re-applies a deferred level change |
| 17:24 operative setpoint drifting down on cover days | ORP samples taken with the pump off (stagnant probe) inflated `pool_orp_fraccion_ok` | fixed 2026-10-05 (D-B): samples only with relay on ≥ 5 min and flow; 05:00 sample stored as 0 when invalid; `n < 8/10` → rules skipped and logged ("sin evidencia") |
| "Alcalinidad baja" never notified while the estimate sat below 55 | `numeric_state … for 2h` needs a crossing; HA restarted already below | fixed 2026-10-05 (D-C): hourly fallback at :05 with a 24 h rate limit |

## Changing the package (checklist)
1. Read the header block and the relevant SPEC section; find the automation/script by alias (`grep -n 'alias: "Piscina ·'`).
2. Invariants: scripts' `variables:` are natively typed (`'1'` becomes int → compare with `| string`; tiny floats render as `5.6e-05` → `round(4)`); MQTT readback sensors need `this.state` guards; new automations need unique `id:`; keep write windows and the ≤ 10 writes / ≤ 3 saves safeguards; recorder-exclude churny sensors; any HA-start side effect belongs in `pool_ha_start`.
3. Jinja checks: never compare str to number; `float(0)`/`int(0)` defaults everywhere; `states.x` may be `none` after restart.
4. For anything beyond a few lines: spawn an implementer agent with the exact spec and an adversarial reviewer (they found the real bugs in every iteration: double counting, races at 17:30, typing); apply the findings.
5. Validate, deploy per `access.md` runbook, verify entities + `pool_plan_verificado`, log in SPEC/ENTITIES/DEPLOY §B and memory.
6. Decision numbering used in the docs: D1 stop pump on no-flow, D2 punta-baja with solar, D3 day share, D4 write budget, D5 pump priority over Tesla, D6/D11 tariff calendar, D9 pump power/flow, D12 pool-day boundary 08:00, D13 cover → only solar overrides, D14 real vs operative redox. Add the next number when you introduce a new owner decision.
