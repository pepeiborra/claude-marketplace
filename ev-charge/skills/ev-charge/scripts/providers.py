"""Provider abstraction for the ev-charge skill.

A `Provider` exposes two operations over a normalized model:

    list_near(bbox)  -> list[Charger]   # chargers inside a bbox
    status(ids)      -> list[Charger]   # live status of specific chargers

`Charger` / `Connector` are provider-agnostic; each adapter maps its source's
raw shape (and raw status codes) into them. A "charger" is the atomic unit the
provider returns: an Iberdrola pedestal (cuprId) or a Repsol station (Waylet
commerce id, connectors flattened across its charge points).

bbox is a 4-tuple (lat_min, lat_max, lon_min, lon_max). Charger ids are native
strings (Iberdrola cuprId as str; Repsol commerce id) — the `provider` field
disambiguates them.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


# Canonical connector statuses (normalized across providers).
FREE_STATUSES = {"AVAILABLE"}
OCCUPIED_STATUSES = {"OCCUPIED", "EV_CONNECTED", "RESERVED"}
OUT_OF_SERVICE_STATUSES = {"OUT_OF_SERVICE", "NOT_OPERATED", "UNDER_CONSTRUCTION"}


@dataclass
class Connector:
    code: str | None
    status: str | None           # canonical status
    type: str | None
    max_kw: float | int | None = None
    price: float | None = None   # EUR/kWh
    evse_id: str | None = None


@dataclass
class Charger:
    provider: str
    charger_id: str
    name: str
    connectors: list[Connector] = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    operator: str | None = None
    address: str | None = None
    # True when latitude/longitude is an approximation (e.g. the grid probe
    # point that discovered a Repsol station, which has no exact coords).
    approx_location: bool = False

    @property
    def free(self) -> int:
        return sum(1 for c in self.connectors if (c.status or "") in FREE_STATUSES)

    @property
    def total(self) -> int:
        return len(self.connectors)

    @property
    def all_out_of_service(self) -> bool:
        if not self.connectors:
            return False
        return all((c.status or "") in OUT_OF_SERVICE_STATUSES for c in self.connectors)


# --- Iberdrola --------------------------------------------------------------


class IberdrolaProvider:
    key = "iberdrola"
    display_name = "Iberdrola"

    def list_near(self, bbox: tuple[float, float, float, float]) -> list[Charger]:
        from client import make_client
        from iberdrola_evcp import BBox

        client = make_client()
        chargers = client.list_chargers(BBox(*bbox))
        if not chargers:
            return []
        return [self._map(d) for d in client.enrich(chargers)]

    def status(self, ids: list[str]) -> list[Charger]:
        from client import make_client

        client = make_client()
        details = client.enrich([int(i) for i in ids])
        return [self._map(d) for d in details]

    def _map(self, d) -> Charger:
        addr = d.address or {}
        pretty = ", ".join(
            x for x in ((addr.get("streetName") or ""), (addr.get("townName") or "")) if x
        ).strip(", ") or None
        return Charger(
            provider=self.key,
            charger_id=str(d.cupr_id),
            name=d.name,
            connectors=[
                Connector(
                    code=s.physical_socket_code,
                    status=s.status,                 # already canonical for Iberdrola
                    type=s.socket_type,
                    max_kw=s.max_power_kw,
                    price=s.price_per_kwh,
                    evse_id=s.evse_id,
                )
                for s in d.sockets
            ],
            latitude=d.latitude,
            longitude=d.longitude,
            operator=d.operator,
            address=pretty,
        )


# --- Repsol -----------------------------------------------------------------


_REPSOL_STATUS = {
    "AVAILABLE": "AVAILABLE",
    "CHARGING": "OCCUPIED",
    "BUSY": "EV_CONNECTED",
    "INOPERATIVE": "OUT_OF_SERVICE",
}
_REPSOL_TYPE = {
    "TYPE_2": "Type 2",
    "COMBO_2": "CCS Combo 2",
    "CHADEMO": "CHAdeMO",
    "TYPE_1": "Type 1",
    "SCHUKO": "Schuko",
}
_KW_RE = re.compile(r"([\d]+(?:[.,]\d+)?)\s*kW", re.IGNORECASE)


class RepsolProvider:
    key = "repsol"
    display_name = "Repsol"

    def list_near(self, bbox: tuple[float, float, float, float]) -> list[Charger]:
        from repsol_evcp import RepsolClient

        client = RepsolClient()
        discovered = client.discover(bbox)
        out: list[Charger] = []
        for sid, (lat, lng) in discovered.items():
            detail = client.detail(sid)
            if not detail:
                continue
            ch = self._map(detail)
            # Coordinates come from the static station finder (real, not the
            # Waylet detail which omits them); good enough for distance sorting.
            ch.latitude, ch.longitude = lat, lng
            out.append(ch)
        return out

    def status(self, ids: list[str]) -> list[Charger]:
        from repsol_evcp import RepsolClient

        client = RepsolClient()
        out: list[Charger] = []
        for sid in ids:
            detail = client.detail(sid)
            if detail:
                out.append(self._map(detail))
        return out

    def _map(self, detail: dict) -> Charger:
        prices = detail.get("prices") or {}
        connectors: list[Connector] = []
        for tier, conns in (detail.get("connectors") or {}).items():
            tier_price = prices.get(tier)
            for c in conns or []:
                connectors.append(
                    Connector(
                        code=c.get("id") or f"{c.get('chargeBoxId')}_{c.get('connectorId')}",
                        status=_REPSOL_STATUS.get(c.get("status"), "UNKNOWN"),
                        type=_REPSOL_TYPE.get(c.get("type"), _pretty(c.get("type"))),
                        max_kw=_parse_kw(c.get("name")),
                        price=(tier_price / 100.0) if isinstance(tier_price, (int, float)) else None,
                        evse_id=c.get("description"),
                    )
                )
        addr = detail.get("address") or {}
        pretty = ", ".join(
            x for x in ((addr.get("street") or ""), (addr.get("city") or "")) if x
        ) or None
        return Charger(
            provider=self.key,
            charger_id=str(detail.get("_id")),
            name=detail.get("name") or f"Repsol {detail.get('_id')}",
            connectors=connectors,
            operator=(detail.get("rmveConfig") or {}).get("operatorName") or detail.get("operatorType"),
            address=pretty,
        )


def _parse_kw(name: str | None) -> float | None:
    if not name:
        return None
    m = _KW_RE.search(name)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _pretty(raw: str | None) -> str | None:
    return raw.replace("_", " ").title() if raw else None


# --- registry ---------------------------------------------------------------

_PROVIDERS = {p.key: p for p in (IberdrolaProvider(), RepsolProvider())}


def make_provider(name: str):
    name = (name or "iberdrola").strip().lower()
    if name not in _PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; expected one of {sorted(_PROVIDERS)}")
    return _PROVIDERS[name]
