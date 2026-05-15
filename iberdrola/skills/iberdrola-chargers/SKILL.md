---
name: iberdrola-chargers
description: Find, check, and monitor Iberdrola EV charging-point availability across Spain. Use this skill whenever the user mentions Iberdrola EV chargers, "puntos de recarga", electric-vehicle charging stations in Spain (Denia, Valencia, Madrid, Bilbao, Alicante, etc.), wants to check if specific chargers are available right now, asks to be warned/notified/pinged when a charger becomes free, wants to set up a watch/loop/poll on charger availability, or mentions cuprId / cuprName. Handles Akamai cookie harvesting via plain HTTP (no headless browser), supports a multi-charger watch flow that polls every 15s and notifies via terminal beep + macOS osascript / Linux notify-send / Windows toast / Telegram. Make sure to use this skill even when the user doesn't say "Iberdrola" explicitly — phrases like "watch Calle Mussola charger" or "warn me when chargers X and Y become free" should trigger it.
---

# Iberdrola EV-charger tools

A toolkit for querying and monitoring the Iberdrola EV charging-point map
API — the same backend behind https://www.iberdrola.es/movilidad-electrica/puntos-de-recarga.

## Setup (do this once at the start of every task)

The scripts live in `scripts/` next to this file. They only need
`requests` from the standard PyPI:

```bash
python3 -c "import requests" 2>/dev/null \
  || pip install --quiet --user requests \
  || pip install --quiet --break-system-packages requests
```

If `pip` is unavailable, suggest `uv pip install requests` or installing
Python from python.org. Don't proceed without `requests` — every script
depends on it.

All scripts use `scripts/client.py` to build an `IberdrolaEVClient` with
freshly-harvested Akamai cookies (one HTTP GET to the public map page).
You don't need to manage cookies by hand.

## Capabilities at a glance

| Task | Script | Notes |
|---|---|---|
| Find chargers near a location | `find_chargers.py` | bbox / center+radius / known place |
| Check status of specific chargers | `charger_status.py` | takes cuprIds |
| Cross-platform desktop notification | `notify.py` | macOS / Linux / Windows + terminal beep |
| Watch chargers and notify when free | (workflow — see below) | combines `charger_status.py` + `/loop` + `notify.py` |

## Dedicated slash command: `/notify-available-charger`

For the watch-and-notify scenario specifically, the plugin ships a
slash command at `commands/notify-available-charger.md`. The user types
`/notify-available-charger <names | cuprIds | location>` and the
command spec (which mirrors Workflow 3 below) runs deterministically —
no triggering ambiguity. Prefer that command when the user wants the
notify-when-free flow.

## Workflow 1: Find chargers near a place

If the user names a Spanish location, look it up in
`references/known_locations.json` first (Denia / Valencia / Madrid /
Barcelona / Bilbao / Alicante are pre-seeded). If the place is there,
use its bbox.

If the place isn't pre-seeded, geocode it: WebFetch
`https://nominatim.openstreetmap.org/search?format=json&q=<place>&limit=1`
to get a `lat/lon`, then call `find_chargers.py --center LAT LON --radius-km 2`.

If the user gives explicit coordinates, pass them through directly.

```bash
# Pre-seeded place
python3 scripts/find_chargers.py --bbox 38.820 38.870 0.060 0.150

# Coordinates + radius
python3 scripts/find_chargers.py --center 38.840 0.106 --radius-km 2

# Free-only filter (€0/kWh — typically municipal slow AC)
python3 scripts/find_chargers.py --center 38.840 0.106 --radius-km 2 --only-free

# Machine-readable
python3 scripts/find_chargers.py --bbox 38.820 38.870 0.060 0.150 --json
```

The default output is a table; `--json` returns one row per pedestal
with cuprId, name, address, free/total, max_kw, min price, distance_km,
and lat/lon. Sort by distance from the bbox/center.

## Workflow 2: Check the status of a specific charger

If the user says "is the charger at <place> available?":

1. **Identify the cuprId(s).** If you've already run `find_chargers.py`
   in this session, you have them. Otherwise run `find_chargers.py`
   for the area and match by name (`cuprName` field). Read aloud what
   you matched so the user can correct you if you picked the wrong one.
2. **Get current status:**
   ```bash
   python3 scripts/charger_status.py 6760 6761
   ```
3. **Summarise** with per-connector breakdown. Statuses you'll see:
   `AVAILABLE` (free), `OCCUPIED`, `EV_CONNECTED` (cable plugged but
   maybe not billing), `OUT_OF_SERVICE`.

Important: one cuprId = one pedestal, which usually has 2 connectors.
"Free" means at least one connector is `AVAILABLE`. Don't double-count
pedestals as "two chargers".

## Workflow 3: "Warn me when charger X (and Y) become free"

This is the central workflow. It combines identification → sanity check
→ a self-pacing `/loop` → multi-channel notification.

### Step 1: Resolve charger names to cuprIds

Same as Workflow 2 — run `find_chargers.py` if you don't already have the
IDs, match by name, confirm with the user. **Show the matched cuprIds
and names before starting the watch** so the user can catch any mismatch.

### Step 2: Rule out chargers that won't change

```bash
python3 scripts/charger_status.py <ID1> <ID2> ...
```

Inspect the output:

- If **all listed chargers are already `AVAILABLE`** — there's nothing
  to wait for. Notify immediately and stop.
- If **any listed charger has `all_out_of_service: true`** — warn the
  user explicitly. Out-of-service can take days to recover. Ask whether
  to proceed anyway or drop that charger.
- If **at least one charger is OCCUPIED / EV_CONNECTED** — good, we
  have something to wait on. Proceed to Step 3.

### Step 3: Set up the watch loop

Use the `loop` skill at a 15-second interval. Hand it a prompt that
embeds the cuprIds and the user's notification preferences. The loop
prompt should:

1. Run `python3 scripts/charger_status.py <IDS> --json`.
2. Parse the JSON and check `free > 0` for **any** of the requested IDs.
3. If any are free: fire notifications and **end the loop** (don't pass
   a continuation prompt to `ScheduleWakeup`, or call `TaskStop` on the
   loop, depending on how the loop skill exposes termination).
4. Otherwise: schedule the next wake-up in 15s.

Concrete invocation (after replacing the IDs and label):

```
/loop 15s "Run python3 $SKILL_DIR/scripts/charger_status.py 6760 6761 --json.
Parse the JSON. If any entry has free > 0, then:
  (a) call $SKILL_DIR/scripts/notify.py --title 'Charger free!' --message
      'Ronda de las Murallas: <free>/<total> connectors AVAILABLE'
  (b) send a Telegram message via the telegram MCP tool if it is
      available (use the same chat_id as the current conversation)
  (c) end the loop (do not schedule the next wake-up).
Otherwise summarise the current state in <80 chars and let the loop
continue."
```

Resolve `$SKILL_DIR` to the actual absolute path of this skill's
directory when constructing the prompt; the loop runs in a fresh
session and won't have that variable.

### Step 4: Notification dispatch

When the loop fires, send notifications through **every available channel**:

- **Terminal beep + desktop notification** (always): run
  `python3 scripts/notify.py --title "..." --message "..."`. It emits a
  triple beep AND tries the right native notifier for the OS.
- **Telegram** (if available): the `telegram:reply` tool is loaded if
  the user has the telegram plugin and an active chat. Use it to send
  the same title + message. The skill itself can't call telegram (no
  credentials baked in), so you (Claude) do it. Pass the `chat_id`
  from the current incoming Telegram message; if none, skip Telegram.
- **Anything else the user wires up**: if you see `slack`, `discord`,
  or similar tools available, send there too with the same payload.

Keep the notification concise: "Charger free!" as title, "Ronda de las
Murallas: 1/4 connectors AVAILABLE" as message.

### Step 5: Confirmation back to the user

After kicking off the watch, briefly tell the user:
- What you're watching (names + cuprIds)
- The poll interval (15s)
- What notifications they'll get and through which channels
- How to stop it (`TaskStop` on the loop, or just ask you to stop)

## Edge cases and gotchas

**`_abck` cookie at `~-1~`**: this is normal. The Iberdrola API only
checks for cookie presence, not Akamai sensor validation. The bundled
client handles this automatically.

**HTTP 403 from the API**: Akamai may have tightened. Re-run the
script — `client.py` harvests fresh cookies every invocation. If it
keeps failing, switch to manual cookies (paste a `cookie:` header from
DevTools) — but that's a last resort.

**Mojibake in charger names** (e.g. `+B Energ�as Denia`): the upstream
data has U+FFFD characters in some roaming-partner names. Not fixable
on our side — present as-is.

**cuprId vs connector**: one cuprId is one physical pedestal with N
connectors (often 2). `free`/`total` counts connectors, not pedestals.
Don't say "X chargers are free" when you mean "X connectors at one
pedestal are free".

**Charge-point type codes**: `P` = Iberdrola-owned ("Propia"), `I` =
third-party roaming partner (Spirii, PowerGo). The letters mean the
opposite of the natural English guess — don't trust intuition here.

**Rate limiting**: Iberdrola's own map UI polls every ~60s. Going
faster than ~10s is unkind. The 15s default for watches is comfortable;
don't shorten it without a reason.

## What this skill does NOT do

- **Reserve, pay, or interact with the charger beyond status.** The
  Iberdrola map API is read-only.
- **Drive an iOS app or run as a server.** For that, point the user
  at the standalone server at `~/scratch/iberdrola/server/` (separate
  project that wraps the same client).
- **Handle EV-charge networks other than Iberdrola.** Other CPOs use
  different APIs (Wenea, EasyCharger, etc.).

## Reference files

- `references/known_locations.json` — pre-seeded bboxes for common
  Spanish cities and Denia. Read whenever the user names a place.

## Bundled scripts

- `scripts/iberdrola_evcp.py` — low-level API client (`IberdrolaEVClient`,
  `BBox`, `Charger`, `ChargerDetail`, `Socket`). Imported by the helpers.
- `scripts/client.py` — `make_client()` factory with HTTP cookie harvest.
- `scripts/find_chargers.py` — list/filter chargers in an area.
- `scripts/charger_status.py` — current status of specific cuprIds.
- `scripts/notify.py` — cross-platform desktop + terminal-beep notifier.
