"""Check the live status of one or more EV chargers, across providers.

Backend-first with a direct-client fallback:

  1. PREFER the monitor backend's GET /api/charger (env EV_CHARGE_BACKEND, else
     http://pipi.local:8765). The backend holds the providers' live clients.
  2. On ANY backend failure (connection refused, timeout, non-200) FALL BACK to
     the bundled direct client so status still works standalone.

Usage:
    python charger_status.py [--provider iberdrola] 6760 6761 98482
    python charger_status.py --provider repsol 5f80107b2ef2880012122cee --json

`--provider` defaults to `iberdrola`. Ids are provider-native:
- iberdrola: cuprId (integer)
- repsol:    Waylet "commerce" id (e.g. 5f80107b2ef2880012122cee)

(The backend keys watches by GLOBAL id "provider:native", but /api/charger
takes native ids + a provider, matching this CLI's shape exactly.)

Output (default): one line per charger with per-connector status.
With --json: array of dicts (provider, charger_id, name, free, total,
all_out_of_service, connectors[]). Pass --no-backend to force the direct client.

Exit codes (useful in a /loop watch):
    0  request succeeded (regardless of free vs occupied)
    1  HTTP / network / auth failure (both backend and fallback failed)
    2  no such charger returned by the API
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import backend  # noqa: E402
from providers import make_provider  # noqa: E402


def _rows_from_backend(provider: str, ids: list[str]) -> list[dict]:
    """Query GET /api/charger; raise backend.BackendUnavailable to fall back."""
    result = backend.charger(provider=provider, ids=ids)
    for err in result.get("errors") or []:
        print(
            f"NOTE: backend provider {err.get('provider')} errored: {err.get('error')}",
            file=sys.stderr,
        )
    return [backend.charger_dict_to_status(d) for d in (result.get("chargers") or [])]


def _rows_from_direct(provider: str, ids: list[str]) -> list[dict]:
    """Query the bundled direct client."""
    p = make_provider(provider)
    chargers = p.status(ids)
    return [
        {
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
        }
        for c in chargers
    ]


def _matched_ids(requested: list[str], payload: list[dict]) -> list[str]:
    """Requested native ids not present in any returned charger_id.

    The backend returns GLOBAL ids ("provider:native") while the direct client
    returns native ids, so match by substring/suffix to cover both.
    """
    returned = {str(r["charger_id"]) for r in payload}
    missing = []
    for i in requested:
        i = str(i)
        if i in returned:
            continue
        if any(rid == i or rid.endswith(":" + i) for rid in returned):
            continue
        missing.append(i)
    return missing


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", default="iberdrola", choices=["iberdrola", "repsol"])
    p.add_argument("charger_ids", nargs="+", type=str)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-backend", action="store_true",
                   help="Skip the backend; use the bundled direct client only.")
    args = p.parse_args()

    payload: list[dict] | None = None
    source = "direct"
    if not args.no_backend:
        try:
            payload = _rows_from_backend(args.provider, args.charger_ids)
            source = "backend"
            print(f"NOTE: using backend at {backend.base_url()}", file=sys.stderr)
        except backend.BackendUnavailable as exc:
            print(
                f"NOTE: backend unavailable ({exc}); falling back to direct client",
                file=sys.stderr,
            )
            payload = None

    if payload is None:
        try:
            payload = _rows_from_direct(args.provider, args.charger_ids)
            source = "direct"
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    missing = _matched_ids(args.charger_ids, payload)
    if missing:
        print(f"WARN: charger id(s) not in API response: {missing}", file=sys.stderr)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 2 if missing and not payload else 0

    print(f"(source={source})", file=sys.stderr)
    for row in payload:
        per_conn = " ".join(
            f"[{cc['code'] or '?'}:{cc['status'] or '?'}]" for cc in row["connectors"]
        )
        flag = " (ALL OUT OF SERVICE)" if row["all_out_of_service"] else ""
        print(f"{str(row['charger_id']):>24}  {row['free']}/{row['total']} free  "
              f"{row['name']}  {per_conn}{flag}")
    return 2 if missing and not payload else 0


if __name__ == "__main__":
    sys.exit(main())
