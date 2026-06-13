"""List EV chargers inside a geographic area, across providers.

Backend-first with a direct-client fallback:

  1. PREFER the monitor backend's GET /api/search (env EV_CHARGE_BACKEND, else
     http://pipi.local:8765). It fans out across every configured network
     (provider=all) and returns live status — including networks the bundled
     direct clients don't speak.
  2. On ANY backend failure (connection refused, timeout, non-200) FALL BACK to
     the bundled direct client (Iberdrola cookie-harvest / Repsol Waylet) so the
     skill still works standalone.

Usage:
    python find_chargers.py [--provider iberdrola|repsol|all] --bbox LAT_MIN LAT_MAX LON_MIN LON_MAX
    python find_chargers.py --provider repsol --center LAT LON [--radius-km 2]

`--provider` defaults to `all` (the backend fans out). When the backend is
down, `all` is treated as the direct-client default `iberdrola` (plus repsol if
asked) — the direct clients can only speak iberdrola/repsol.

By default writes a table to stdout. With `--json` emits one row per charger
with provider, charger_id, name, address, free/total, max_kw, min price,
distance_km, lat/lon. Pass `--no-backend` to force the direct client.

Note on Repsol via the direct client: discovery sweeps a coarse grid against
the Waylet nearest-commerce endpoint, so coordinates (and therefore
distance_km) are APPROXIMATE; the `approx` flag marks these. The backend
returns exact coordinates.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import backend  # noqa: E402
from providers import make_provider  # noqa: E402

# Providers the bundled direct clients can speak (the fallback set).
DIRECT_PROVIDERS = ("iberdrola", "repsol")


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


def _rows_from_backend(
    provider: str,
    center: tuple[float, float],
    radius_km: float,
    bbox: tuple[float, float, float, float],
) -> list[dict]:
    """Query the backend; raise backend.BackendUnavailable to trigger fallback."""
    result = backend.search(provider=provider, bbox=bbox)
    chargers = result.get("chargers") or []
    errors = result.get("errors") or []
    for err in errors:
        print(
            f"NOTE: backend provider {err.get('provider')} errored: {err.get('error')}",
            file=sys.stderr,
        )
    rows = []
    for d in chargers:
        row = backend.charger_dict_to_row(d)
        if row["latitude"] is not None and row["longitude"] is not None:
            row["distance_km"] = round(
                haversine_km(center[0], center[1], row["latitude"], row["longitude"]), 2
            )
        rows.append(row)
    return rows


def _rows_from_direct(
    provider: str,
    center: tuple[float, float],
    bbox: tuple[float, float, float, float],
) -> list[dict]:
    """Query the bundled direct client(s) for one or more providers."""
    # When the backend is down and provider=='all', the direct clients can only
    # speak iberdrola/repsol — sweep both.
    targets = DIRECT_PROVIDERS if provider == "all" else [provider]
    rows: list[dict] = []
    for prov in targets:
        if prov not in DIRECT_PROVIDERS:
            print(
                f"NOTE: no direct client for provider {prov!r}; skipping (needs the backend)",
                file=sys.stderr,
            )
            continue
        try:
            p = make_provider(prov)
            chargers = p.list_near(bbox)
        except Exception as exc:  # noqa: BLE001 — isolate per provider
            print(f"NOTE: direct client {prov} failed: {exc}", file=sys.stderr)
            continue
        for c in chargers:
            max_kw = max((x.max_kw for x in c.connectors if x.max_kw), default=None)
            prices = [x.price for x in c.connectors if x.price is not None]
            min_price = min(prices) if prices else None
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
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", default="all",
                   choices=["iberdrola", "repsol", "all"])
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
    p.add_argument("--no-backend", action="store_true",
                   help="Skip the backend; use the bundled direct client only.")
    args = p.parse_args()

    if args.bbox:
        bbox = (args.bbox[0], args.bbox[1], args.bbox[2], args.bbox[3])
        center = ((bbox[0] + bbox[1]) / 2, (bbox[2] + bbox[3]) / 2)
        radius_km = args.radius_km
    else:
        lat, lon = args.center
        bbox = bbox_from_center(lat, lon, args.radius_km)
        center = (lat, lon)
        radius_km = args.radius_km

    rows: list[dict] | None = None
    source = "direct"
    if not args.no_backend:
        try:
            rows = _rows_from_backend(args.provider, center, radius_km, bbox)
            source = "backend"
            print(f"NOTE: using backend at {backend.base_url()}", file=sys.stderr)
        except backend.BackendUnavailable as exc:
            print(
                f"NOTE: backend unavailable ({exc}); falling back to direct client",
                file=sys.stderr,
            )
            rows = None

    if rows is None:
        rows = _rows_from_direct(args.provider, center, bbox)
        source = "direct"

    # Apply free-only filter + sort + cap (uniform across both sources).
    filtered = []
    for r in rows:
        mp = r.get("min_price_eur_per_kwh")
        if args.only_free and (mp is None or mp > 0):
            continue
        filtered.append(r)
    rows = filtered

    if not rows:
        print(json.dumps([]) if args.json else f"(no chargers in area; source={source})")
        return 0

    rows.sort(key=lambda r: (r["distance_km"] if r["distance_km"] is not None else 1e9,
                             str(r["charger_id"])))
    rows = rows[: args.max_rows]

    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
        return 0

    label = args.provider if args.provider != "all" else "all-network"
    print(f"{len(rows)} {label} chargers (source={source}, sorted by distance from center)\n")
    hdr = ("charger_id", "free", "kW", "EUR/kWh", "name", "address", "dist")
    widths = [24, 5, 5, 7, 30, 30, 6]
    print("  ".join(f"{h:<{w}}" for h, w in zip(hdr, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        if r["distance_km"] is None:
            dist = "-"
        elif r.get("approx"):
            dist = "~" + f"{r['distance_km']:.1f}"
        else:
            dist = f"{r['distance_km']:.2f}"
        cells = (
            str(r["charger_id"]),
            f"{r['free']}/{r['total']}",
            "-" if r["max_kw"] is None else f"{r['max_kw']:g}",
            "-" if r["min_price_eur_per_kwh"] is None else f"{r['min_price_eur_per_kwh']:g}",
            (r["name"] or "")[:30],
            (r["address"][:30]).strip(", "),
            dist,
        )
        print("  ".join(f"{cell:<{w}}" for cell, w in zip(cells, widths)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
