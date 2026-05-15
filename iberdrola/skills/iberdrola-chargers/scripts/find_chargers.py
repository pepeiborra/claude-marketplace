"""List chargers inside a geographic bounding box.

Usage:
    python find_chargers.py --bbox LAT_MIN LAT_MAX LON_MIN LON_MAX
    python find_chargers.py --center LAT LON [--radius-km 2]
    python find_chargers.py --place denia

The third form looks the place up in `references/known_locations.json`
(read by the caller and passed as --bbox or --center for portability).

By default writes a table to stdout. With `--json` emits the raw shape
the skill body promises (one row per pedestal with id, name, address,
free/total, status, distance_km).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import make_client
from iberdrola_evcp import BBox  # noqa: E402


def bbox_from_center(lat: float, lon: float, radius_km: float) -> BBox:
    """Approximate bbox of a circle in WGS84 — good enough for this scale."""
    # 1 deg latitude ≈ 111 km. Longitude shrinks by cos(lat).
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(lat)) or 1.0)
    return BBox(
        lat_min=lat - dlat,
        lat_max=lat + dlat,
        lon_min=lon - dlon,
        lon_max=lon + dlon,
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--bbox", nargs=4, type=float,
                   metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"))
    g.add_argument("--center", nargs=2, type=float, metavar=("LAT", "LON"))
    p.add_argument("--radius-km", type=float, default=2.0,
                   help="Used with --center (default 2 km).")
    p.add_argument("--only-free", action="store_true",
                   help="Filter to chargers priced at 0 €/kWh after enriching.")
    p.add_argument("--json", action="store_true")
    p.add_argument("--max-rows", type=int, default=200)
    args = p.parse_args()

    if args.bbox:
        bbox = BBox(args.bbox[0], args.bbox[1], args.bbox[2], args.bbox[3])
        center = ((bbox.lat_min + bbox.lat_max) / 2, (bbox.lon_min + bbox.lon_max) / 2)
    else:
        lat, lon = args.center
        bbox = bbox_from_center(lat, lon, args.radius_km)
        center = (lat, lon)

    client = make_client()
    chargers = client.list_chargers(bbox)
    if not chargers:
        if args.json:
            print(json.dumps([]))
        else:
            print("(no chargers in bbox)")
        return 0

    # Enrich for per-socket + price data.
    details = {d.cupr_id: d for d in client.enrich(chargers)}

    rows = []
    for c in chargers:
        d = details.get(c.cupr_id)
        if d is None:
            continue
        prices = [s.price_per_kwh for s in d.sockets if s.price_per_kwh is not None]
        min_price = min(prices) if prices else None
        if args.only_free and (min_price is None or min_price > 0):
            continue
        free = sum(1 for s in d.sockets if s.status == "AVAILABLE")
        total = len(d.sockets)
        max_kw = max((s.max_power_kw for s in d.sockets if s.max_power_kw), default=None)
        rows.append({
            "cupr_id": d.cupr_id,
            "name": d.name,
            "address": (d.address.get("streetName") or "") + ", " + (d.address.get("townName") or ""),
            "free": free,
            "total": total,
            "rollup_status": d.rollup_status,
            "max_kw": max_kw,
            "min_price_eur_per_kwh": min_price,
            "type_code": d.type_code,
            "distance_km": round(haversine_km(center[0], center[1], d.latitude, d.longitude), 2),
            "latitude": d.latitude,
            "longitude": d.longitude,
            "operator": d.operator,
        })

    rows.sort(key=lambda r: (r["distance_km"], r["cupr_id"]))
    rows = rows[: args.max_rows]

    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
        return 0

    print(f"{len(rows)} chargers (sorted by distance from center)\n")
    hdr = ("cuprId", "free", "kW", "€/kWh", "name", "address", "dist")
    widths = [8, 5, 5, 6, 36, 36, 6]
    print(("  ".join(f"{h:<{w}}" for h, w in zip(hdr, widths))))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        cells = (
            str(r["cupr_id"]),
            f"{r['free']}/{r['total']}",
            "-" if r["max_kw"] is None else f"{r['max_kw']}",
            "-" if r["min_price_eur_per_kwh"] is None else f"{r['min_price_eur_per_kwh']:g}",
            (r["name"] or "")[:36],
            (r["address"][:36]).strip(", "),
            f"{r['distance_km']:.2f}",
        )
        print("  ".join(f"{c:<{w}}" for c, w in zip(cells, widths)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
