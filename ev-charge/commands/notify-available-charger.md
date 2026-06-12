---
description: Find an EV charger (Iberdrola or Repsol) that is free right now, or start a 15s monitor and notify when one becomes available. Accepts charger names, ids, locations, or free-form descriptions.
argument-hint: <charger names | ids | location | "near coords"> [iberdrola|repsol]
allowed-tools: Bash, Read, Skill, ScheduleWakeup, WebFetch
---

The user invoked `/notify-available-charger` with this input:

```
$ARGUMENTS
```

Carry out the workflow below. The bundled `ev-charge` skill at this plugin's `skills/ev-charge/` has everything you need — read its `SKILL.md` once and follow the workflows there. Do NOT reinvent the network calls. Every script takes `--provider iberdrola|repsol` (default `iberdrola`).

## Step 1 — Parse the input

The argument is free-form. It may contain any mix of:

- **A network**: "iberdrola", "repsol", or "waylet". If named, use it as `--provider`. If not named, infer from context (a Repsol station name → repsol; a cuprId / "puntos de recarga" → iberdrola); when a bare location is given and the user wants ANY charger, consider checking BOTH networks.
- **Specific charger names** (e.g. "Calle Mussola", "Ronda de las Murallas", "Repsol CRED Denia")
- **ids** — Iberdrola cuprIds (4-7 digit numbers) or Repsol Waylet commerce ids (24-char hex). Only treat as ids if context makes it clear.
- **Place / area descriptions** ("near plaza del marquesado in denia", "valencia centro")
- **Coordinates** ("38.84, 0.10", "lat 38.84 lon 0.10")
- **Power / cost filters** ("any 50 kW near me", "the free €0 ones in alicante")

If the input is ambiguous, **make a reasonable assumption and proceed** rather than asking — note your assumption (including which network) in one line so the user can correct you. If truly unparseable (empty, or "the closest one" with no location), ask for clarification.

## Step 2 — Resolve to ids (and the provider)

Pick the strategy that fits the input:

- **If ids given directly**: use them with the matching `--provider`. No lookup needed.
- **If charger name + implied location**: look the location up in `references/known_locations.json` first (Denia, Valencia, Madrid, Barcelona, Bilbao, Alicante are pre-seeded). If not pre-seeded, geocode via Nominatim. Then run `find_chargers.py --provider <P> --bbox ...` (or `--center`) and fuzzy-match the name.
- **If location only ("watch chargers near X")**: run `find_chargers.py --provider <P> --center LAT LON --radius-km 2`. If the user didn't name a network, run it for BOTH iberdrola and repsol and merge. Treat all chargers in the area as the watch set; if there are more than ~10, ask the user to narrow (or use `--only-free`).
- **If coordinates given**: pass directly to `--center LAT LON`.

**Always** show the user the resolved list (`provider — id — name — address`) in 1-2 lines per charger before starting the watch, so they can catch a mismatch.

## Step 3 — Check current status

```bash
python3 <plugin>/skills/ev-charge/scripts/charger_status.py --provider <P> <ID1> <ID2> ... --json
```

(Resolve `<plugin>` to the absolute path; the loop runs in a fresh session and won't know symbolic paths. Run once per provider if the watch set spans both networks.)

Parse the JSON.

## Step 4 — Branch on current state

- **If any matched charger has `free > 0` RIGHT NOW**: nothing to wait for. Fire notifications immediately (Step 6), tell the user which is free, and stop. Do NOT start a loop.
- **If ALL matched chargers have `all_out_of_service: true`**: warn the user (OOS can take days to recover) and ask whether to proceed or drop the OOS ones. Don't start the loop until they confirm.
- **Otherwise** (at least one OCCUPIED / EV_CONNECTED / mixed): proceed to Step 5.

## Step 5 — Start the watch

Use the `loop` skill at a 15-second interval. The loop runs in a fresh session, so embed everything as literal values (provider, ids, plugin absolute path, the user's label for the chargers, any active Telegram chat_id). If watching both networks, embed one `charger_status.py --provider ...` call per network in the loop prompt.

Example invocation pattern:

```
/loop 15s "Run python3 /abs/path/to/ev-charge/scripts/charger_status.py --provider repsol <IDS...> --json.
Parse the JSON output. If ANY entry has free > 0:
  (a) Run python3 /abs/path/to/ev-charge/scripts/notify.py
        --title 'Charger free!'
        --message '<friendly description>: <free>/<total> AVAILABLE at <name>'
  (b) If the telegram MCP tool is available, send the same message via telegram:reply
      to chat_id <CHAT_ID> (current chat).
  (c) END the loop — do not call ScheduleWakeup again; the watch is done.
Otherwise summarise the current state in under 80 chars and let the loop continue."
```

After kicking off the loop, **do not poll yourself** — notifications arrive in whatever channels the user wired up.

## Step 6 — Notification dispatch (used by both immediate-hit and loop-fires-later)

Send through every available channel:

- **Desktop + terminal beep** (always): run `notify.py` with `--title "Charger free!"` and a one-line message naming the network, charger, and free count.
- **Telegram** (if the `telegram:reply` MCP tool is available): send the same payload to the current chat. Pass `chat_id` from the incoming message context.
- **Slack/Discord/etc.** if you see those tools loaded.

The skill itself doesn't send to remote channels (no credentials baked in) — you (Claude) do it using whatever messaging tools the user has connected.

## Step 7 — Confirm to the user

End the command's first turn with a short summary:

- What you resolved (network + ids + names)
- Current status snapshot (free/occupied per charger)
- Whether you notified immediately or started a watch
- If watching: interval (15s), channels, how to stop (`TaskStop` on the loop or "stop watching the chargers")

## Examples

**Input:** `Calle Mussola`
→ iberdrola. Resolve to cuprId 98482 via known_locations[denia_urban] + find_chargers. Check status; if free notify, else loop.

**Input:** `the Repsol charger at CRED Denia`
→ repsol. find_chargers --provider repsol --center 38.84 0.10 --radius-km 3, match "CRED Denia" → commerce id. Check status; loop if occupied.

**Input:** `any free charger near plaza del marquesado, denia`
→ Geocode → coords near (38.836, 0.109). Run find_chargers for BOTH iberdrola and repsol --center 38.836 0.109 --radius-km 1, merge, take the closest few, watch all.

**Input:** `6760, 6761, 98494`
→ iberdrola cuprIds directly. Check status. Watch any not already free.
