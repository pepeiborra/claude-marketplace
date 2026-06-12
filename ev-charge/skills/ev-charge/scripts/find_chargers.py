"""List EV chargers inside a geographic bounding box, across providers.

Usage:
    python find_chargers.py [--provider iberdrola|repsol] --bbox LAT_MIN LAT_MAX LON_MIN LON_MAX
    python find_chargers.py --provider repsol --center LAT LON [--radius-km 2]

`--provider` defaults to `iberdrola`. By default writes a table to stdout.
With `--json` emits one row per charger with provider, charger_id, name,
address, free/total, max_kw, min price, distance_km, and lat/lon.

Note on Repsol: discovery sweeps a coarse grid of the bbox against the Waylet
nearest-commerce endpoint, so coordinates (and therefore distance_km) are
APPROXIMATE — each station inherits the probe point that found it. The `approx`
flag in the JSON/table marks these.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from providers import make_provider  # noqa: E402


def bbox_from_center(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Approximate bbox of a circle in WGS84 — good enough for this scale."""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(lat)) or 1.0)
    return (lat - dlat, lat + dlat, lon - dlon, lon + dlon)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", default="iberdrola", choices=["iberdrola", "repsol"])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--bbox", nargs=4, type=float,
                   metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"))
    g.add_argument("--center", nargs=2, type=float, metavar=("LAT", "LON"))
    p.add_argument("--radius-km", type=float, default=2.0,
                   help="Used with --center (default 2 km).")
    p.add_argument("--only-free", action="store_true",
                   help="Filter to chargers priced at 0 EUR/kWh.")
    p.add_argument("--json", action="store_true")
    p.add_argument("--max-rows", type=int, default=200)
    args = p.parse_args()

    if args.bbox:
        bbox = (args.bbox[0], args.bbox[1], args.bbox[2], args.bbox[3])
        center = ((bbox[0] + bbox[1]) / 2, (bbox[2] + bbox[3]) / 2)
    else:
        lat, lon = args.center
        bbox = bbox_from_center(lat, lon, args.radius_km)
        center = (lat, lon)

    try:
        provider = make_provider(args.provider)
        chargers = provider.list_near(bbox)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not chargers:
        print(json.dumps([]) if args.json else "(no chargers in bbox)")
        return 0

    rows = []
    for c in chargers:
        prices = [x.price for x in c.connectors if x.price is not None]
        min_price = min(prices) if prices else None
        if args.only_free and (min_price is None or min_price > 0):
            continue
        max_kw = max((x.max_kw for x in c.connectors if x.max_kw), default=None)
        if c.latitude is not None and c.longitude is not None:
            dist = round(haversine_km(center[0], center[1], c.latitude, c.longitude), 2)
        else:
            dist = None
        rows.append({
            "provider": c.provider,
            "charger_id": c.charger_id,
            "name": c.name,
            "address": c.address or "",
            "free": c.free,
            "total": c.total,
            "max_kw": max_kw,
            "min_price_eur_per_kwh": min_price,
            "distance_km": dist,
            "approx": c.approx_location,
            "latitude": c.latitude,
            "longitude": c.longitude,
            "operator": c.operator,
        })

    rows.sort(key=lambda r: (r["distance_km"] if r["distance_km"] is not None else 1e9,
                             r["charger_id"]))
    rows = rows[: args.max_rows]

    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
        return 0

    print(f"{len(rows)} {args.provider} chargers (sorted by distance from center)\n")
    hdr = ("charger_id", "free", "kW", "EUR/kWh", "name", "address", "dist")
    widths = [16, 5, 5, 7, 34, 34, 6]
    print("  ".join(f"{h:<{w}}" for h, w in zip(hdr, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        if r["distance_km"] is None:
            dist = "-"
        elif r["approx"]:
            dist = "~" + f"{r['distance_km']:.1f}"
        else:
            dist = f"{r['distance_km']:.2f}"
        cells = (
            str(r["charger_id"]),
            f"{r['free']}/{r['total']}",
            "-" if r["max_kw"] is None else f"{r['max_kw']:g}",
            "-" if r["min_price_eur_per_kwh"] is None else f"{r['min_price_eur_per_kwh']:g}",
            (r["name"] or "")[:34],
            (r["address"][:34]).strip(", "),
            dist,
        )
        print("  ".join(f"{cell:<{w}}" for cell, w in zip(cells, widths)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
