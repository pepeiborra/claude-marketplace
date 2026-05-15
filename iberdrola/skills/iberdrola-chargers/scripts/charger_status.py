"""Check the live status of one or more chargers by cuprId.

Usage:
    python charger_status.py 6760 6761 98482
    python charger_status.py --json 6760 6761

Output (default): one line per pedestal with per-connector status.
With --json: array of detail dicts (cupr_id, name, free, total, sockets[]).

Exit codes (useful in a /loop watch):
    0  request succeeded (regardless of free vs occupied)
    1  HTTP / network / Akamai failure
    2  no such cuprId returned by the API
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import make_client


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cupr_ids", nargs="+", type=int)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    try:
        client = make_client()
        details = client.enrich(args.cupr_ids)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    found = {d.cupr_id for d in details}
    missing = [i for i in args.cupr_ids if i not in found]
    if missing:
        print(f"WARN: cuprId(s) not in API response: {missing}", file=sys.stderr)

    payload = []
    for d in details:
        connectors = []
        for s in d.sockets:
            connectors.append({
                "code": s.physical_socket_code,
                "type": s.socket_type,
                "status": s.status,
                "max_kw": s.max_power_kw,
                "price_eur_per_kwh": s.price_per_kwh,
            })
        free = sum(1 for s in d.sockets if s.status == "AVAILABLE")
        all_oos = all(s.status == "OUT_OF_SERVICE" for s in d.sockets) if d.sockets else False
        payload.append({
            "cupr_id": d.cupr_id,
            "name": d.name,
            "rollup_status": d.rollup_status,
            "free": free,
            "total": len(d.sockets),
            "all_out_of_service": all_oos,
            "address": (d.address.get("streetName") or "") + ", " + (d.address.get("townName") or ""),
            "connectors": connectors,
        })

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 2 if missing and not payload else 0

    for row in payload:
        per_conn = " ".join(
            f"[{c['code'] or '?'}:{c['status'] or '?'}]" for c in row["connectors"]
        )
        flag = " (ALL OUT OF SERVICE)" if row["all_out_of_service"] else ""
        print(f"{row['cupr_id']:>8}  {row['free']}/{row['total']} free  "
              f"{row['rollup_status']:<14}  {row['name']}  {per_conn}{flag}")
    return 2 if missing and not payload else 0


if __name__ == "__main__":
    sys.exit(main())
