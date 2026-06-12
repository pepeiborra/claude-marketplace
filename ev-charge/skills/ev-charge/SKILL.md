---
name: ev-charge
description: Find, check, and monitor EV charging-point availability in Spain across multiple networks — Iberdrola and Repsol (Waylet). Use this skill whenever the user mentions EV chargers / charging stations / "puntos de recarga" in Spain (Denia, Valencia, Madrid, Bilbao, Alicante, etc.), names Iberdrola or Repsol/Waylet, wants to check if specific chargers are available right now, asks to be warned/notified/pinged when a charger becomes free, wants to set up a watch/loop/poll on charger availability, or mentions cuprId / cuprName / a Repsol station. Each network has a direct client (no backend server needed): Iberdrola via Akamai cookie harvesting over plain HTTP, Repsol via the unauthenticated Waylet RMVE API (live per-connector status). Supports a multi-charger watch flow that polls every 15s and notifies via terminal beep + macOS osascript / Linux notify-send / Windows toast / Telegram. Trigger even when the user doesn't name a network — phrases like "watch Calle Mussola charger", "is the Repsol charger in Denia free", or "warn me when chargers X and Y become free" should all trigger it.
---

# EV-charge tools

A toolkit for querying and monitoring EV charging-point availability in Spain
across networks. Two providers are supported today, each with its own direct
client (no backend server involved):

- **`iberdrola`** — the Iberdrola map API
  (https://www.iberdrola.es/movilidad-electrica/puntos-de-recarga). Behind
  Akamai; cookies are harvested automatically over plain HTTP. A charger is a
  *pedestal* identified by a numeric `cuprId`.
- **`repsol`** — the public Waylet RMVE API (`pro.waylet.es`), the same live
  data behind Repsol's "scan-and-charge" web flow. No login/cookie needed. A
  charger is a *station* ("commerce") identified by a Waylet id like
  `5f80107b2ef2880012122cee`; its connectors are flattened across the station's
  charge points.

Every script takes `--provider iberdrola|repsol` (default `iberdrola`).

## Setup (do this once at the start of every task)

The scripts live in `scripts/` next to this file. They only need `requests`:

```bash
python3 -c "import requests" 2>/dev/null \
  || pip install --quiet --user requests \
  || pip install --quiet --break-system-packages requests
```

If `pip` is unavailable, suggest `uv pip install requests` or installing
Python from python.org. Don't proceed without `requests`.

## Capabilities at a glance

| Task | Script | Notes |
|---|---|---|
| Find chargers near a location | `find_chargers.py --provider P` | bbox / center+radius |
| Check status of specific chargers | `charger_status.py --provider P <ids>` | takes native ids |
| Cross-platform desktop notification | `notify.py` | macOS / Linux / Windows + beep |
| Watch chargers and notify when free | (workflow — see below) | `charger_status.py` + `/loop` + `notify.py` |

## Choosing a provider

- If the user names **Repsol** or **Waylet** → `--provider repsol`.
- If the user names **Iberdrola**, a **cuprId**, or "puntos de recarga" → `--provider iberdrola` (the default).
- If the user just names a place and wants **any** charger ("any free charger near X"),
  you can run `find_chargers.py` once **per provider** and merge the results — present
  them grouped by network. Don't assume one network; Spain has both.
- When unsure and it matters, say which network you're checking so the user can redirect you.

## Dedicated slash command: `/notify-available-charger`

For the watch-and-notify scenario, the plugin ships a slash command at
`commands/notify-available-charger.md`. The user types
`/notify-available-charger <names | ids | location>` and the command runs the
watch flow deterministically. Prefer it for the notify-when-free flow.

## Workflow 1: Find chargers near a place

If the user names a Spanish location, look it up in
`references/known_locations.json` first (Denia / Valencia / Madrid / Barcelona /
Bilbao / Alicante are pre-seeded). If not pre-seeded, geocode it: WebFetch
`https://nominatim.openstreetmap.org/search?format=json&q=<place>&limit=1` to get
`lat/lon`, then use `--center LAT LON --radius-km 2`. If the user gives explicit
coordinates, pass them through.

```bash
# Iberdrola (default), pre-seeded place
python3 scripts/find_chargers.py --bbox 38.820 38.870 0.060 0.150

# Repsol, near a point
python3 scripts/find_chargers.py --provider repsol --center 38.840 0.106 --radius-km 3

# Free-only filter (0 EUR/kWh — typically municipal slow AC; rare on Repsol)
python3 scripts/find_chargers.py --center 38.840 0.106 --radius-km 2 --only-free

# Machine-readable
python3 scripts/find_chargers.py --provider repsol --bbox 38.80 38.88 0.00 0.20 --json
```

`--json` returns one row per charger with `provider`, `charger_id`, name,
address, free/total, max_kw, min price, distance_km, lat/lon. Rows are sorted by
distance. **Repsol coordinates** come from Repsol's static station finder and
are reliable; live free/total comes from Waylet.

## Workflow 2: Check the status of a specific charger

1. **Identify the id(s).** If you've run `find_chargers.py` this session, you
   have them. Otherwise run it for the area and match by name. Read aloud what
   you matched so the user can correct you.
2. **Get current status** (note the matching `--provider`):
   ```bash
   python3 scripts/charger_status.py 6760 6761                       # iberdrola cuprIds
   python3 scripts/charger_status.py --provider repsol 5f80107b2ef2880012122cee
   ```
3. **Summarise** per-connector. Canonical statuses across both networks:
   `AVAILABLE` (free), `OCCUPIED`, `EV_CONNECTED` (cable in / busy),
   `OUT_OF_SERVICE`. "Free" means at least one connector is `AVAILABLE`.

One id = one pedestal (Iberdrola) or one station (Repsol), each with several
connectors. `free`/`total` counts connectors, not pedestals/stations.

## Workflow 3: "Warn me when charger X (and Y) become free"

The central workflow: identification → sanity check → a self-pacing `/loop` →
multi-channel notification. (The `/notify-available-charger` command automates it.)

### Step 1: Resolve names to ids (and the provider)

Run `find_chargers.py --provider P` if you don't have the ids; match by name;
**show the matched provider + ids + names before starting the watch.**

### Step 2: Rule out chargers that won't change

```bash
python3 scripts/charger_status.py --provider P <ID1> <ID2> ...
```

- **All already `AVAILABLE`** → nothing to wait for; notify immediately and stop.
- **Any with `all_out_of_service: true`** → warn explicitly (OOS can take days);
  ask whether to proceed or drop it.
- **At least one OCCUPIED / EV_CONNECTED** → proceed to Step 3.

### Step 3: Set up the watch loop

Use the `loop` skill at a 15-second interval, embedding the provider, ids, and
notification preferences as literal values (the loop runs in a fresh session).

```
/loop 15s "Run python3 $SKILL_DIR/scripts/charger_status.py --provider repsol 5f80107b2ef2880012122cee --json.
Parse the JSON. If any entry has free > 0, then:
  (a) call $SKILL_DIR/scripts/notify.py --title 'Charger free!' --message
      'Repsol CRED Denia: <free>/<total> connectors AVAILABLE'
  (b) send a Telegram message via the telegram MCP tool if available
      (same chat_id as the current conversation)
  (c) end the loop (do not schedule the next wake-up).
Otherwise summarise the current state in <80 chars and let the loop continue."
```

Resolve `$SKILL_DIR` to this skill's absolute directory when building the prompt.

### Step 4: Notification dispatch

Fire through **every available channel**:

- **Terminal beep + desktop notification** (always): `python3 scripts/notify.py
  --title "..." --message "..."` (triple beep + the right native notifier).
- **Telegram** (if `telegram:reply` is available): same title + message, using
  the `chat_id` from the current chat. The skill can't call Telegram itself.
- **Slack/Discord/etc.** if those tools are loaded.

### Step 5: Confirmation

Tell the user what you're watching (provider + names + ids), the interval (15s),
the channels, and how to stop (`TaskStop` on the loop, or ask you to stop).

## Edge cases and gotchas

**Iberdrola — `_abck` cookie at `~-1~`**: normal. The API only checks cookie
presence. `client.py` re-harvests fresh cookies every invocation. On HTTP 403,
just re-run; if it keeps failing, Akamai may have tightened.

**Iberdrola — mojibake in names** (e.g. `+B Energ�as`): upstream data has U+FFFD
characters in some roaming-partner names. Present as-is.

**Iberdrola — type codes**: `P` = Iberdrola-owned ("Propia"), `I` = third-party
roaming partner. The letters mean the opposite of the natural English guess.

**Repsol — no auth, but undocumented**: the Waylet RMVE API needs no cookie/login.
It's an internal endpoint; be polite (the client paces requests). Repsol raw
statuses map to the canonical enum: `BUSY`→`EV_CONNECTED`, `CHARGING`→`OCCUPIED`,
`INOPERATIVE`→`OUT_OF_SERVICE`.

**Repsol — ids differ from coordinates**: live status is keyed by the Waylet
"commerce" id; `find_chargers.py` discovers those by cross-referencing Repsol's
static station finder (which has coordinates). If `find_chargers` finds a station
but `charger_status` returns nothing for its id, the station may be offline in Waylet.

**Rate limiting**: the map UIs poll ~every 60s. The 15s watch interval is
comfortable; don't go below ~10s.

## What this skill does NOT do

- **Reserve, pay, or interact beyond reading status.** Both APIs are read-only here.
- **Run as a server / drive an iOS app.** For that, see the standalone server at
  `~/scratch/iberdrola/server/` (separate project; same providers, with history,
  notifications, and a dashboard).
- **Networks other than Iberdrola and Repsol** (yet). Adding one means a new
  `*_evcp.py` client + an adapter in `scripts/providers.py`.

## Reference files

- `references/known_locations.json` — pre-seeded bboxes for common Spanish
  cities and Denia. Read whenever the user names a place. Provider-agnostic.

## Bundled scripts

- `scripts/providers.py` — provider abstraction: normalized `Charger`/`Connector`
  model + `make_provider("iberdrola"|"repsol")`. Each adapter exposes
  `list_near(bbox)` and `status(ids)`.
- `scripts/iberdrola_evcp.py` — low-level Iberdrola API client.
- `scripts/repsol_evcp.py` — low-level Repsol Waylet RMVE client (+ static
  station-finder discovery).
- `scripts/client.py` — Iberdrola HTTP cookie-harvest factory (`make_client()`).
- `scripts/find_chargers.py` — list/filter chargers in an area (`--provider`).
- `scripts/charger_status.py` — current status of specific ids (`--provider`).
- `scripts/notify.py` — cross-platform desktop + terminal-beep notifier.
