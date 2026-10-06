# Description optimization (2026-10-06)

Harness: skill-creator `run_loop.py` (candidate descriptions registered as temp command files, `claude -p` headless, read-only shim `--allowed-tools Skill,Read`), 20 trigger queries in `trigger_eval.json` (12 train / 8 test), 3 iterations, 2 runs per query, timeout 90 s.

Result: `best_description` == original (train 9/12, test 6/8). Precision 100 % (no false triggers on Tesla / Sonoff / aquarium / generic HA queries) but recall only ~25 %: should-trigger queries fired 0–50 % in that harness, so the loop could not discriminate between candidates. The harness itself was the bottleneck (headless triggering of command-file skills is erratic), not the wording.

Root cause found afterwards: the `piscina` plugin was **not installed** (the `~/scratch/marketplace` directory was not a registered marketplace), so in real sessions the skill was never offered at all. Fixed with `claude plugin marketplace add ~/scratch/marketplace` + `claude plugin install piscina@marketplace` (user scope, enabled).

Hand-tuned description (v0.2.1): kept the original scope sentence, added the Spanish vocabulary the owner actually uses (depuradora, clorador, célula, alcalinidad, dKH, programador, excedente, horas punta…), explicit "even without the word pool" examples (he medido 3 dKH, la bomba hace ruido, HA no responde) and a negative clause (Tesla/solar packages, other Tasmota/Sonoff, heat pumps, other pools). No `: ` sequences or double quotes in the value — the frontmatter is a plain YAML scalar and the first attempt broke parsing.

Smoke test with the plugin installed (headless, read-only, 3/3 triggered on the first turn):
- "he medido 3 dKH y el pH está en 7.6, ¿qué hago?" → Skill piscina:piscina
- "la bomba hace un ruido raro desde ayer" → Skill piscina:piscina
- "¿cómo va la piscina? ¿hay algo que atender?" → Skill piscina:piscina

Before the fix the first query (plugin absent) was answered as an aquarium question.
