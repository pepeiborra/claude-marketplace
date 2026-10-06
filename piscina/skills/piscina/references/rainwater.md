# Rainwater refill to lower calcium hardness

## Setup (owner, Sept–Oct 2026)
House in Dénia (Marina Alta — AEMET orange zone for heavy rain). Roof ≈ 130 m² of clay tiles, aluminium gutters, 6 downpipes (2 at ~10 m hidden among planters, 1 at 15 m, 3 at 20–25 m), downpipe Ø ≈ 8 cm. No tank, no gutter cutting: removable flat 100 mm hose (Carrefour "plastocanal", 0.38 €/m) slipped over the outside of the downpipe end and tied, run to the pool with 2–5 cm of fall; 75 mm adapters for the far ones. Hoses are deployed only during rain episodes.

## Math (keep these numbers)
- Roof 130 m² × 0.85 runoff ≈ 110 L per mm + 50 L per mm falling on the pool → **160 L per mm of rain → 3.2 mm of pool level per mm of rain** (3.6 if runoff were 100 %).
- Dilution by overflow (pool full, inflow Q): CH = 750 × e^(−Q/60). Drain-then-fill: 750 × (1 − Q/60). The difference is small (50 mm: 656 vs 654), so draining is only a buffer against overflow, not a dilution gain.
- Table (from 750): 10 mm → 730; 20 → 711; 30 → 693; 50 → 656; 80 → 606; 100 → 574; 150 → 503. 33 cm drained (16.5 m³, 27.5 %) needs ~103 mm to refill and gives ≈ 545 if filled with rain.
- Downpipes at 50 mm/h intensity move ≈ 1.8 L/s in total; the 100 mm flat hose copes even with little fall.

## Procedure
1. Only drain on an official AEMET warning with ≥ 40 mm expected; drain 10 cm (skimmer lip) for 40–60 mm, 30–40 cm for 100–150 mm. Use the pump to waste in Manual **after** setting `input_boolean.pool_mantenimiento` on (otherwise the watchdog returns the controller to Auto and R5b fires on FL1).
2. Returns above the water → aeration → pH spikes and acid destroys TA: switch the scheduler to cover mode (low speed) or pause filtration until refilled; consider pH max 7.6 temporarily.
3. First-flush: keep hoses off for the first 5–10 min of rain or use a filter sock; expect to clean skimmer basket and filter afterwards.
4. After the episode: restore `pool_mantenimiento`/cover mode as appropriate, run the pump, then measure salt (cell `LOW` below ~2.5–2.8 g/L; 25 kg salt ≈ +0.42 g/L), KH (bicarbonate: 1 kg = +9.9 ppm), CYA (0.5 kg ≈ +8 ppm), FC (liquid chlorine shock), and re-baseline the TA model. Record mm fallen and the new CH (drop kit) in memory; update `input_number.pool_calcium_hardness` so the LSI is right.
5. Repeat on later episodes; two 100 mm events bring CH near 400.

## Long-term hardness plan
Cover (less evaporation), softened/decalcified top-up water, rainwater episodes. Rejected: tank, cutting gutters, "No More Scale" / PoolTiger (cavitation) as primary solutions.
