---
name: ev-charge
description: Find, check, and monitor EV charging-point availability in Spain across multiple networks — Iberdrola, Repsol (Waylet), and any others the optional backend adds (Zunder, Eranovum). Use this skill whenever the user mentions EV chargers / charging stations / "puntos de recarga" in Spain (Denia, Valencia, Madrid, Bilbao, Alicante, etc.), names Iberdrola or Repsol/Waylet, wants to check if specific chargers are available right now, asks to be warned/notified/pinged when a charger becomes free, wants to set up a watch/loop/poll or server-side monitor on charger availability, or mentions cuprId / cuprName / a Repsol station. It PREFERS a backend monitor server (multi-provider fan-out, live status, history, and a server-side watch subsystem) but FALLS BACK to bundled direct clients (Iberdrola via Akamai cookie harvesting, Repsol via the unauthenticated Waylet RMVE API) so search + status still work with no backend. Supports both a client-side watch flow (polls every 15s, notifies via terminal beep + macOS osascript / Linux notify-send / Windows toast / Telegram) AND a backend-side monitor (register chargers, the server polls and notifies). Trigger even when the user doesn't name a network — phrases like "watch Calle Mussola charger", "is the Repsol charger in Denia free", or "warn me when chargers X and Y become free" should all trigger it.
---

# EV-charge tools

A toolkit for querying and monitoring EV charging-point availability in Spain
across networks.

## Backend-first, with a direct-client fallback

The skill PREFERS a **backend monitor server** and FALLS BACK to **bundled
direct clients** when no backend is reachable:

- **Backend (preferred).** A standalone monitor server (`~/scratch/iberdrola/`,
  also deployable to a Pi) exposes a `/api` contract. It fans out across every
  configured network in one call (`provider=all`), returns live status with
  exact coordinates and a uniform `charger_dict` shape, can speak networks the
  direct clients can't (Zunder, Eranovum), and hosts the **server-side watch
  subsystem** (register chargers → the server's poller notifies you when one
  frees up). `find_chargers.py` and `charger_status.py` hit it first.
- **Direct clients (fallback).** When the backend is down, `find_chargers.py`
  and `charger_status.py` transparently fall back to per-network direct clients,
  so the skill still works fully standalone for **search + status**:
  - **`iberdrola`** — the Iberdrola map API. Behind Akamai; cookies are
    harvested automatically over plain HTTP. A charger is a *pedestal*
    identified by a numeric `cuprId`.
  - **`repsol`** — the public Waylet RMVE API (`pro.waylet.es`). No login. A
    charger is a *station* identified by a Waylet id like
    `5f80107b2ef2880012122cee`; connectors are flattened across charge points.

**`EV_CHARGE_BACKEND` env var** sets the backend base URL (default
`http://pipi.local:8765`). Point it at a local server (e.g.
`http://127.0.0.1:8765`) for testing. All backend calls have short timeouts
(~8s) so a missing/slow backend degrades quickly to the fallback path — the
skill never hangs on the network.

**How the fallback is decided:** any connection-refused, DNS failure, timeout,
or non-2xx HTTP from the backend raises `BackendUnavailable`; `find_chargers` /
`charger_status` catch it and re-run via the direct client. Each script prints a
one-line `NOTE:` to stderr saying which path it used (`source=backend` vs
`source=direct`), and `--no-backend` forces the direct client.

**The server-side monitor (`monitor_chargers.py`) is BACKEND-ONLY** — the
watch/poll subsystem has no standalone fallback. If the backend is unreachable
it fails with a clear "needs the backend" message (use `charger_status.py` +
`/loop` for client-side watching instead; see Workflow 3).

The legacy provider summary (still accurate for the direct-client fallback):

- **`iberdrola`** — the Iberdrola map API
  (https://www.iberdrola.es/movilidad-electrica/puntos-de-recarga). Behind
  Akamai; cookies are harvested automatically over plain HTTP. A charger is a
  *pedestal* identified by a numeric `cuprId`.
- **`repsol`** — the public Waylet RMVE API (`pro.waylet.es`), the same live
  data behind Repsol's "scan-and-charge" web flow. No login/cookie needed. A
  charger is a *station* ("commerce") identified by a Waylet id like
  `5f80107b2ef2880012122cee`; its connectors are flattened across the station's
  charge points.

`find_chargers.py` takes `--provider iberdrola|repsol|all` (default `all` — the
backend fans out; when falling back, `all` sweeps both direct clients).
`charger_status.py` takes `--provider iberdrola|repsol` (default `iberdrola`).

## Setup (do this once at the start of every task)

The scripts live in `scripts/` next to this file. The backend path
(`monitor_chargers.py`, and `find_chargers`/`charger_status` while the backend
is up) is **stdlib-only** — no install needed. The direct-client fallback needs
`requests`; install it so the fallback works if the backend is ever down:

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
| Find chargers near a location | `find_chargers.py [--provider P]` | backend-first → direct fallback; bbox / center+radius |
| Check status of specific chargers | `charger_status.py --provider P <ids>` | backend-first → direct fallback; native ids |
| Server-side monitor (register / list / unregister watches) | `monitor_chargers.py register\|list\|unregister` | **backend-only**; the server polls + notifies |
| Cross-platform desktop notification | `notify.py` | macOS / Linux / Windows + beep |
| Client-side watch + notify when free | (workflow — see below) | `charger_status.py` + `/loop` + `notify.py` |

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
# All networks (default — backend fans out; falls back to direct clients)
python3 scripts/find_chargers.py --bbox 38.820 38.870 0.060 0.150

# Constrain to one network
python3 scripts/find_chargers.py --provider repsol --center 38.840 0.106 --radius-km 3

# Free-only filter (0 EUR/kWh — typically municipal slow AC; rare on Repsol)
python3 scripts/find_chargers.py --center 38.840 0.106 --radius-km 2 --only-free

# Machine-readable
python3 scripts/find_chargers.py --provider repsol --bbox 38.80 38.88 0.00 0.20 --json

# Force the bundled direct client (skip the backend)
python3 scripts/find_chargers.py --no-backend --center 38.840 0.106 --radius-km 3
```

Default `--provider all`: via the backend this returns every network in one
call; on the fallback path it sweeps the two direct clients (iberdrola + repsol)
and merges. `--json` returns one row per charger with `provider`, `charger_id`,
name, address, free/total, max_kw, min price, distance_km, lat/lon. Rows are
sorted by distance. **Backend** `charger_id` is a GLOBAL id (`provider:native`)
and coordinates are exact; the **direct-client Repsol** path uses native ids and
approximate coordinates from the static station finder (the `~`-prefixed
distances). A `NOTE:` on stderr says `source=backend` or `source=direct`.

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

## Two ways to "warn me when a charger frees up"

There are two monitoring modes; pick based on whether the backend is reachable:

- **Backend-side monitor (preferred when the backend is up)** — Workflow 4.
  Register chargers on the server; its background poller watches them and fires
  notifications. Survives this session ending. **Requires the backend.**
- **Client-side watch loop (always available)** — Workflow 3. A self-pacing
  `/loop` polls `charger_status.py` every 15s and notifies locally. Works with
  no backend (the status calls fall back to the direct clients), but only lasts
  as long as the loop/session runs.

When the backend is reachable, prefer Workflow 4. The
`/notify-available-charger` command picks the right mode automatically.

## Workflow 3: client-side watch loop ("warn me when charger X becomes free")

The client-side workflow: identification → sanity check → a self-pacing `/loop`
→ multi-channel notification. Works with no backend (status falls back to direct
clients). For a durable server-side monitor, prefer Workflow 4.

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

## Workflow 4: backend-side monitor (durable, server polls + notifies)

**Requires the backend.** Hand a set of chargers to the server's watch
subsystem; its background poller checks them every cycle and fires a
notification on a busy→free transition. This survives the session ending — no
client-side loop. If the backend is unreachable, `monitor_chargers.py` fails
with a clear "needs the backend" message; fall back to Workflow 3.

Typical flow — search, find everything busy, monitor them, check back later:

```bash
# 1. Find chargers (backend); note their GLOBAL charger_ids (provider:native).
python3 scripts/find_chargers.py --center 38.840 0.106 --radius-km 2 --json

# 2. All busy → register the ones to watch (global ids, or --provider + native).
python3 scripts/monitor_chargers.py register iberdrola:6760 repsol:5f80107b2ef2880012122cee
python3 scripts/monitor_chargers.py register --provider iberdrola 6760 6761   # equivalent

# 3. Later, "check my monitors" — shows each watch + a FREED UP section.
python3 scripts/monitor_chargers.py list

# 4. Stop watching some/all.
python3 scripts/monitor_chargers.py unregister iberdrola:6760
```

Ids passed to the monitor are GLOBAL (`provider:native`) — exactly the
`charger_id` that `find_chargers.py` returns on the backend path. `register`
maps to `POST /api/watch`, `list` to `GET /api/watches`, `unregister` to
`DELETE /api/watch`. A freshly-registered watch shows "not yet polled" until the
server's next poll cycle (default 60s), after which `list` shows live free/total
+ status and surfaces freed-up chargers. The server delivers the actual
notification (desktop / Telegram / web push, per its own config) — you don't
need a client-side loop. Use `--ttl-s` to bound how long a watch lives.

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

**Rate limiting**: the map UIs poll ~every 60s. The 15s client-side watch
interval is comfortable; don't go below ~10s. The backend monitor paces itself
(default 60s poll) — don't try to poll `monitor_chargers.py list` faster than
that; the server only refreshes once per cycle.

**Backend unavailable**: `find_chargers` / `charger_status` print a `NOTE:` and
fall back to the direct clients automatically — nothing to do. Only
`monitor_chargers.py` hard-requires the backend; if it errors, set
`EV_CHARGE_BACKEND` correctly (or start the server) and retry, or use the
Workflow 3 client-side loop instead.

**Backend reachable but a provider errors**: the backend isolates per-provider
failures and returns them in `errors[]`; the scripts print each as a `NOTE:` and
still return the other networks' chargers. (E.g. Waylet rate-limiting Eranovum
shows as one note, not a total failure.)

## What this skill does NOT do

- **Reserve, pay, or interact beyond reading status.** All APIs are read-only here.
- **Run as a server / drive an iOS app.** The skill is a *client*: it prefers
  the standalone server at `~/scratch/iberdrola/server/` (separate project —
  history, notifications, dashboard, and the watch subsystem) and falls back to
  direct clients. It does not run that server.
- **Monitor without a backend.** Server-side monitoring (`monitor_chargers.py`)
  needs the backend; without it, only the client-side `/loop` watch (Workflow 3)
  is available.
- **Speak networks beyond Iberdrola and Repsol via the direct fallback.** The
  backend can add more (Zunder, Eranovum); the bundled direct clients only do
  iberdrola + repsol. Adding a direct client means a new `*_evcp.py` + an adapter
  in `scripts/providers.py`.

## Reference files

- `references/known_locations.json` — pre-seeded bboxes for common Spanish
  cities and Denia. Read whenever the user names a place. Provider-agnostic.

## Bundled scripts

- `scripts/backend.py` — stdlib-only HTTP client for the monitor backend
  (`/api/search`, `/api/charger`, `/api/providers`, `/api/watch[es]`). Resolves
  `EV_CHARGE_BACKEND` (default `http://pipi.local:8765`), short timeouts, raises
  `BackendUnavailable` on any failure (the fallback trigger), and maps the
  backend's `charger_dict` into the skill's row shapes.
- `scripts/find_chargers.py` — list/filter chargers in an area. Backend-first
  (`--provider all` fans out) → direct-client fallback. `--no-backend` to force.
- `scripts/charger_status.py` — current status of specific native ids
  (`--provider`). Backend-first → direct-client fallback. `--no-backend` to force.
- `scripts/monitor_chargers.py` — **backend-only** server-side watch:
  `register` / `list` / `unregister` (POST/GET/DELETE `/api/watch[es]`).
- `scripts/providers.py` — direct-client provider abstraction: normalized
  `Charger`/`Connector` + `make_provider("iberdrola"|"repsol")`, each exposing
  `list_near(bbox)` and `status(ids)`. Used on the fallback path.
- `scripts/iberdrola_evcp.py` — low-level Iberdrola API client.
- `scripts/repsol_evcp.py` — low-level Repsol Waylet RMVE client (+ static
  station-finder discovery).
- `scripts/client.py` — Iberdrola HTTP cookie-harvest factory (`make_client()`).
- `scripts/notify.py` — cross-platform desktop + terminal-beep notifier.
