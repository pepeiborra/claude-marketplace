"""Check the live status of one or more EV chargers, across providers.

Usage:
    python charger_status.py [--provider iberdrola] 6760 6761 98482
    python charger_status.py --provider repsol 5f80107b2ef2880012122cee --json

`--provider` defaults to `iberdrola`. Ids are provider-native:
- iberdrola: cuprId (integer)
- repsol:    Waylet "commerce" id (e.g. 5f80107b2ef2880012122cee)

Output (default): one line per charger with per-connector status.
With --json: array of dicts (provider, charger_id, name, free, total,
all_out_of_service, connectors[]).

Exit codes (useful in a /loop watch):
    0  request succeeded (regardless of free vs occupied)
    1  HTTP / network / auth failure
    2  no such charger returned by the API
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from providers import make_provider  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", default="iberdrola", choices=["iberdrola", "repsol"])
    p.add_argument("charger_ids", nargs="+", type=str)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    try:
        provider = make_provider(args.provider)
        chargers = provider.status(args.charger_ids)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    found = {c.charger_id for c in chargers}
    missing = [i for i in args.charger_ids if str(i) not in found]
    if missing:
        print(f"WARN: charger id(s) not in API response: {missing}", file=sys.stderr)

    payload = []
    for c in chargers:
        payload.append({
            "provider": c.provider,
            "charger_id": c.charger_id,
            "name": c.name,
            "free": c.free,
            "total": c.total,
            "all_out_of_service": c.all_out_of_service,
            "address": c.address or "",
            "connectors": [
                {
                    "code": x.code,
                    "type": x.type,
                    "status": x.status,
                    "max_kw": x.max_kw,
                    "price_eur_per_kwh": x.price,
                }
                for x in c.connectors
            ],
        })

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 2 if missing and not payload else 0

    for row in payload:
        per_conn = " ".join(
            f"[{cc['code'] or '?'}:{cc['status'] or '?'}]" for cc in row["connectors"]
        )
        flag = " (ALL OUT OF SERVICE)" if row["all_out_of_service"] else ""
        print(f"{row['charger_id']:>24}  {row['free']}/{row['total']} free  "
              f"{row['name']}  {per_conn}{flag}")
    return 2 if missing and not payload else 0


if __name__ == "__main__":
    sys.exit(main())
