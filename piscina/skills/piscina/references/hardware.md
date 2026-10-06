# Hardware and troubleshooting ladders

## Controller: Hayward AquaRite+ (Sugar Valley NeoPool)
- Modules: hydrolysis (cell 22 g/h max; `Hydrolysis.Percent.Setpoint` 100), redox control (`REDOX_EN`), pH control (acid relay 1, min 7.0 / max 7.4), cover input (not wired; HA has its own cover mode). Filtration modes 0 Manual / 1 Auto / 3 Smart (never) / 13 Backwash.
- Cell states in FAST: `Pol1`/`Pol2` producing (polarity alternation), `Flow` = no FL1, `OFF` = stopped (redox `ON_TARGET` reached, or mode), `LOW` = salt low. `gh` = g/h now (22 when at 100 %), `pct` = demand %. `cell_current` ≈ 220 and `pwm` ≈ 13–15 k are raw register units (not mA/V); the pwm needed for the same current rises with low salt and cold water (ratio pwm/current ~61 healthy → ~66 at 2.4 g/L, 23 °C) and the controller raises `Low` when it hits MAX_VOLTAGE.
- Power module history (08-2026): 12 V rail sag (`rail_12v_mv`) and an intermittent Pol2 leg fault were diagnosed with the 1 Hz poller, repaired at a workshop; a dirty cell was swapped. Reference: `10-fault-analysis.md`, `README.md`.
- Clock: no reliable RTC behaviour under Modbus contention — keep the HA auto-resync; the controller restores the NPSave'd clock on some events.
- Display actions by the owner (Manual, ESC, pause) show up as mode changes without a historial line.

## Atom (M5 Atom Lite + Tail485, Tasmota)
- WiFi is weak at the equipment room (RSSI watch in the Alta frecuencia view). Uptime weeks; `Status 7` for NTP/TZ (`Timezone 99` with EU DST rules). Rules: Rule1 watchdog (340 chars) + Rule2 clock sync in `tasmota_rules.txt`.
- Modbus bus: ~6 % no-response under poller load; writes to the controller (timers, time) can be corrupted — always verify by readback.

## Pump: Hayward MaxFlo VS (SP2310, 1 CV)
- Speeds used: V1 1500 rpm 110 W (baja, 6.9 m³/h), V2 2720 rpm 470 W (media, 12.5 m³/h), V3 3000 rpm 626 W (alta, priming 300 s on every relay start). One skimmer + bottom suction, so the pump can run with the level below the skimmer (just no surface skimming).
- Noise checklist: (1) strainer lid air leak (vaso with air/vortex, O-ring dry/cracked → silicone grease, lid firm), (2) suction restriction/cavitation (skimmer basket, valves, low level, bubbles at returns), (3) debris in the impeller (gravel/marbles rattle, open the diffuser with the breaker off), (4) motor bearings (whine rising with rpm, grinding when turning the fan shaft by hand), (5) shaft seal (drip/scale under the pump), (6) mounting/pipes (hum/vibration), (7) filter pressure +25 % → backwash the glass filter. Compare the sound at low (night) vs media (afternoon): since the scheduler the pump runs more hours at media (≈ 13–14 h/day) and fewer total (≈ 16 vs 22.7 before).
- Dry running damages the seal: the package stops and suspends after 1 h without FL1; when the owner drains to waste with the pump in Manual, put the scheduler in maintenance first.

## Chlorinator "is failing" ladder
1. Is the cell producing right now? FAST `gh > 0`, `state Pol1/Pol2`, `cell_current ≈ 220`. If `state = Flow` → no FL1 (pump off, air, filter). If `OFF` with pump on → redox at/above the operative setpoint (`ON_TARGET`, by design), `LOW` salt, or module disabled.
2. How many hours/day has it produced lately? `scripts/poller_report.py 10` (columns cloro_g, h_cel vs pump total). Healthy: ≈ 22 g/h × pump hours. If h_cel ≪ pump hours at night → operative redox setpoint below the night ORP plateau (710–730 mV); raise it (R2b) — this was the 2026-09-21..30 regression.
3. Production fine but FC low? CYA < 20 (UV burn), pH > 7.6 (less HOCl), heavy load/rain dilution, bather load → more pump hours (chlor_hours) or liquid chlorine shock.
4. Production erratic: rails (`rail_12v_mv` < 12 000 or `rail_2430v_mv` < 26 000 → power module), polarity leg (`Pol2` with gh 0 → leg fault), cell scaled (CH 750! acid-clean the cell: 1:10 HCl soak until bubbling stops, never scrape), cell end of life (current drops with pct 100 → `pool_cell_health.yaml` detector).
5. Salt: cell `LOW` flag or display "Low salt" → measure (strips/refractometer), add salt to 3.2 g/L (25 kg ≈ +0.42 g/L in 60 m³).

## Acid pump (peristaltic, relay 1)
See chemistry.md §Acid dosing line for the full ladder. Mechanical essentials: Santoprene head tube (replace when it stops occluding; never after mixing H₂SO₄/HCl), suction tube 4×6 PVC with foot valve + strainer (Astral 4408030123 type), injector check valve on the pipe before the cell (scales at CH 750), drum 1.8 m below the pump (keep it there: fumes away from the electronics), pump exhaust/drip tray.

## Probes
- pH and redox probes upstream of the injector; readings invalid when the pump is off (stagnant). Redox probe cleaning: HCl 1:10, rinse; calibration solution 468 mV. pH calibration with the controller's routine (buffers 7/4 or 7/10) if persistent offset vs DPD/drop tests.

## Raspberry Pi health
- 4 GB, zram + disk swap; normal: ~1.5 GB used, swap near 0, load < 1, `poolfast` tasks ≈ 11, HA container ~500 MB RSS.
- Symptoms of trouble: HA login fails/timeouts, ssh banner timeout, load > 5, swap > 1 GB. Check `ps -eo rss,etime,args --sort=-rss | head -15`, `pgrep -fc "docker exec mosquitto mosquitto_sub"` (should be 1), `docker stats`.
- Known incident 2026-09-28: poller leaked one `docker exec … mosquitto_sub` per relaunch (bad UTF-8 byte → exception → relaunch without kill): 230 clients, 2.6 GB swap. Fixed in `poller.py` (`errors="replace"`, `reap_subscriber()`); recovery `sudo systemctl restart poolfast` + `docker exec mosquitto pkill -f "stat/aquarite/RESULT -t tele/aquarite/SENSOR"`.
- Never run HA `check_config` on the Pi; never `immutable=1` on the recorder DB; the owner also runs a `claude` loop in tmux on the Pi (~300 MB) — leave it alone.
- HA restart ≈ 3–4 min; MQTT reconnects ~10 s; FAST sensors `unavailable` for a minute; readbacks arrive 3 min after start.
