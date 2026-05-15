---
description: Find an Iberdrola EV charger that is free right now, or start a 15s monitor and notify when one becomes available. Accepts charger names, cuprIds, locations, or free-form descriptions.
argument-hint: <charger names | cuprIds | location | "near coords">
allowed-tools: Bash, Read, Skill, ScheduleWakeup, WebFetch
---

The user invoked `/notify-available-charger` with this input:

```
$ARGUMENTS
```

Carry out the workflow below. The bundled `iberdrola-chargers` skill at this plugin's `skills/iberdrola-chargers/` has everything you need — read its `SKILL.md` once and follow the workflows there. Do NOT reinvent the network calls.

## Step 1 — Parse the input

The argument is free-form. It may contain any mix of:

- **Specific charger names** (e.g. "Calle Mussola", "Ronda de las Murallas", "Mercadona Saladar")
- **cuprIds** (4-7 digit numbers — only treat as IDs if context makes it clear)
- **Place / area descriptions** ("near plaza del marquesado in denia", "valencia centro", "around the marina")
- **Coordinates** ("38.84, 0.10", "lat 38.84 lon 0.10")
- **Network / power filters** ("any 50 kW near me", "the free €0 ones in alicante")
- **Combinations** ("Calle Mussola or any free charger in Ronda de las Murallas")

If the input is ambiguous, **make a reasonable assumption and proceed** rather than asking — note your assumption in one line so the user can correct you. If it's truly unparseable (e.g. empty, or "the closest one" with no location context), ask for clarification.

## Step 2 — Resolve to cuprIds

Pick the strategy that fits the input:

- **If cuprIds given directly**: use them. No lookup needed.
- **If charger name + implied location**: look the location up in `references/known_locations.json` first (Denia, Valencia, Madrid, Barcelona, Bilbao, Alicante are pre-seeded). If not pre-seeded, geocode via Nominatim. Then run `find_chargers.py --bbox ...` and fuzzy-match the name against `cuprName`.
- **If location only ("watch chargers near X")**: run `find_chargers.py --center LAT LON --radius-km 2`. By default treat ALL chargers in the area as the watch set (this is "find me ANY available charger near X"). If there are more than 10, ask the user to narrow down (or use `--only-free` if they said anything about cost).
- **If coordinates given**: pass directly to `--center LAT LON`.

**Always** show the user the resolved list (`cuprId — name — address`) in 1-2 lines per charger before starting the watch. Make it possible for them to catch a mismatch.

## Step 3 — Check current status

```bash
python3 <plugin>/skills/iberdrola-chargers/scripts/charger_status.py <ID1> <ID2> ... --json
```

(Resolve `<plugin>` to the absolute path; the loop runs in a fresh session and won't know symbolic paths.)

Parse the JSON.

## Step 4 — Branch on current state

- **If any matched charger has `free > 0` RIGHT NOW**: there's nothing to wait for. Fire notifications immediately (see Step 6), tell the user which one is free, and stop. Do NOT start a loop.

- **If ALL matched chargers have `all_out_of_service: true`**: warn the user — OOS can take days to recover — and ask whether to proceed anyway or drop the OOS ones. Don't start the loop until they confirm.

- **Otherwise** (at least one is OCCUPIED / EV_CONNECTED / mixed): proceed to Step 5.

## Step 5 — Start the watch

Use the `loop` skill at a 15-second interval. The loop runs in a fresh session, so embed everything it needs as literal values (cuprIds, plugin absolute path, the user's identifier for the chargers, and any active Telegram chat_id).

Example invocation pattern:

```
/loop 15s "Run python3 /abs/path/to/iberdrola-chargers/scripts/charger_status.py <IDS...> --json.
Parse the JSON output. If ANY entry has free > 0:
  (a) Run python3 /abs/path/to/iberdrola-chargers/scripts/notify.py
        --title 'Charger free!'
        --message '<friendly description>: <free>/<total> AVAILABLE at <name>'
  (b) If the telegram MCP tool is available, send the same message via telegram:reply
      to chat_id <CHAT_ID> (current chat).
  (c) END the loop — do not call ScheduleWakeup again; the watch is done.
Otherwise summarise the current state in under 80 chars and let the loop continue."
```

After kicking off the loop, **do not poll yourself** — the notifications will arrive in whatever channels the user has wired up.

## Step 6 — Notification dispatch (used by both immediate-hit and loop-fires-later)

Send through every available channel:

- **Desktop + terminal beep** (always): run `notify.py` with `--title "Charger free!"` and a one-line message naming the charger and the free count.
- **Telegram** (if the `telegram:reply` MCP tool is available): send the same payload to the current chat. Pass `chat_id` from the incoming message context.
- **Slack/Discord/etc.** if you see those tools loaded: send there too.

The skill itself doesn't send to remote channels (no credentials baked in) — you (Claude) do it using whatever messaging tools the user has connected.

## Step 7 — Confirm to the user

End the command's first turn with a short summary:

- What you resolved (names + cuprIds)
- Current status snapshot (free/occupied per charger)
- Whether you notified immediately or started a watch
- If watching: interval (15s), channels you'll notify through, how to stop (`TaskStop` on the loop or "stop watching the chargers")

## Examples

**Input:** `Calle Mussola`
→ Resolve to cuprId 98482 via known_locations[denia_urban] + find_chargers. Check status. If free, notify; otherwise loop.

**Input:** `Ronda de las Murallas 01 or 02`
→ Resolve to [6760, 6761]. Watch BOTH; fire as soon as either has a free connector.

**Input:** `any free charger near plaza del marquesado, denia`
→ Geocode plaza del marquesado → coords near (38.836, 0.109). find_chargers --center 38.836 0.109 --radius-km 1. Take the closest 3-5. Watch all.

**Input:** `the 50 kW DC ones at the marina`
→ Find chargers in the marina area, filter to max_kw >= 50, present list, watch them.

**Input:** `6760, 6761, 98494`
→ cuprIds directly. Check status. Watch any that aren't already free.
