# Dashboard "Piscina" (`pool-diagnostics.yaml`, YAML mode)

Registered in `configuration.yaml` (`lovelace: dashboards: pool-diagnostics:` title "Piscina", icon `mdi:pool`); the old storage dashboard "Aquarite" and "ClorationPump" are hidden/retired. Views (`path`): `pool` (Piscina: overview — temperature, pH & redox, chlorination charts, controls), `programador` (Programador: estado, plan de hoy/mañana, horas cumplidas vs objetivo, redox objetivo vs operativa, plan vs real, speed chart, ORP de día vs consigna, controles manuales y overrides), `cloracion` (Cloración: g/h, %, demand, polarity, rails, flags), `alta-frecuencia` (poller signals, Atom health), `alcalinidad` (acid-drum model, inputs dKH/ppm, bicarbonate, acid type, pump parameters, LSI live + 7-day chart, pH alarm).

## Patterns used (copy them)
- Time range selector shared by all charts: `input_select.pool_chart_range` (1h…30d) read by `custom:config-template-card` which sets `span` and `gb` (group-by) variables:
  ```yaml
  - type: custom:config-template-card
    variables:
      span: "{ '1h':'1h','6h':'6h','24h':'24h','7d':'7d','30d':'30d' }[states['input_select.pool_chart_range'].state]"
      gb: "{ '1h':'1min','6h':'5min','24h':'15min','7d':'1h','30d':'6h' }[states['input_select.pool_chart_range'].state]"
    entities: [input_select.pool_chart_range, sensor.pool_redox]
    card:
      type: custom:apexcharts-card
      graph_span: ${span}
      header: { show: true, title: "${'pH & Redox — ' + span + ' (mediana ' + gb + ')'}" }
      series:
        - entity: sensor.pool_redox
          name: Redox
          group_by: { func: median, duration: ${gb} }
        - entity: input_number.pool_redox_objetivo
          name: Objetivo
          curve: stepline
          stroke_dash: 4
  ```
- `type: markdown` cards with Jinja for status text (see "Plan de hoy": reads `state_attr('sensor.pool_plan_hoy','historial')`).
- `type: entities` for inputs/switches; `type: history-graph` for binary timelines; `type: button` calling `script.*`.
- Custom cards available: `config-template-card`, `apexcharts-card` (≥ 2.x, supports `stroke_dash`, `group_by`, `statistics`).

## Adding a long-range aggregate (e.g. monthly mean water temperature)
Raw states purge after 30 days, so anything monthly/seasonal must come from **long-term statistics** (hourly mean/min/max kept forever for sensors with `state_class: measurement`). Two water-temperature sensors qualify: `sensor.piscina_aquarite_plus_neopool_temperature` (Tasmota; LTS since 2026-07-22, longest history, hourly min/max contain Modbus glitches — use mean only) and `sensor.pool_water_temp` (pool_mqtt.yaml, explicit `state_class: measurement`, LTS since 2026-09-08). Check `statistics_meta` on the Pi before choosing. Prefer the native `statistics-graph` (no custom-card dependency) unless you need the apexcharts look. Two options:
1. Core card, zero config:
   ```yaml
   - type: statistics-graph
     title: Temperatura del agua — media mensual
     entities: [sensor.piscina_aquarite_plus_neopool_temperature]
     period: month
     stat_types: [mean, min, max]
     days_to_show: 365
   ```
2. apexcharts with statistics (consistent style with the rest):
   ```yaml
   - type: custom:apexcharts-card
     graph_span: 365d
     header: { show: true, title: Temperatura media por mes }
     series:
       - entity: sensor.piscina_aquarite_plus_neopool_temperature
         statistics: { type: mean, period: month }
         type: column
   ```
Place it in the view the owner names (default: `pool`, after the temperature chart) and keep card titles in Spanish.

## Workflow
1. Edit `~/scratch/atom-pool/pool-diagnostics.yaml`; keep indentation of the surrounding view; quote names containing `:`.
2. `ruby -ryaml -e 'YAML.load_file("pool-diagnostics.yaml")'`.
3. Deploy with backup (`access.md` runbook) but **do not restart HA for a dashboard-only change**: YAML dashboards are re-read when the owner uses ⋮ → Actualizar or reloads the browser (verified 2026-10-05). Restart only if a new sensor/package was added.
4. Verify in the browser or ask the owner; note the change in `SCHEDULER-DEPLOY.md` §B.
5. If the new card needs a new sensor, add it to the right package and remember recorder excludes for churny ones; sensors meant for monthly stats need `state_class: measurement` and a `unit_of_measurement`.
