"""Reverse-engineered client for Iberdrola's EV charging-point map API.

Endpoint family (POST, JSON in / JSON out):

    https://www.iberdrola.es/o/webclipb/iberdrola/puntosrecargacontroller/<op>

Three observed operations:

    getGruposListarPuntosRecarga   — aggregated map clusters for a bbox
    getListarPuntosRecarga         — individual chargers in a bbox
    getDatosPuntoRecarga           — full detail (sockets, prices, status) by cuprId

The API has no auth, but the host is behind Akamai Bot Manager. Calls without
a valid `_abck` / `ak_bmsc` / `bm_sz` cookie set get HTTP 403 from the edge.
The simplest way to obtain those cookies is to visit
https://www.iberdrola.es/movilidad-electrica/puntos-de-recarga in a real
browser and copy the `cookie:` header; pass it via `cookie_header=`.
Cookies survive long enough to drive many calls; refresh from the browser
when calls start returning 403.

Response envelope:

    {
      "seguro": bool,                # session-related flag, always false here
      "errorAjax": str|null,         # error string if call failed at app layer
      "tiempo": int,                 # server epoch millis
      "seg": null,
      "entidad": [...],              # the actual payload
      "errores": ...,
      "serviceException": ...,
    }

Empirically observed enum values (likely non-exhaustive):

    chargePointTypeCode    "P" iberdrola-own, "I" roaming partner, "R", "N"
    situationCode          "OPER" operative, "EC_APR" under-approval, ...
    cpStatus.statusCode    "AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE",
                           "EV_CONNECTED" (statusId 1/2/4/...). NOTE: this
                           field is a per-cuprId *rollup*; the per-connector
                           state lives in
                           `logicalSocket[*].status.statusCode` and is only
                           returned by the detail endpoint.
    socketTypeId           "2" Mennekes (AC Type-2 socket), "5" Tipo2-cable
                           (AC Type-2 with cable), "6" Chademo (DC),
                           "7" Combo-Tipo2 (CCS Type-2 DC) — confirmed
                           against samples; ids may extend.
    appliedRate.typeRate   "pr" per-recharge price (€/kWh in `price`/`finalPrice`)

Topology: one cuprId == one physical pedestal. Pedestals typically have
multiple connectors, modelled as `logicalSocket[]`, each holding one
`physicalSocket[]` entry. The list endpoint reports `socketNum` (total
connectors) and a rollup `cpStatus`, but omits per-connector rate/status.
Call the detail endpoint (or `IberdrolaEVClient.enrich()`) to get
connector-level state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import requests


BASE_URL = "https://www.iberdrola.es/o/webclipb/iberdrola/puntosrecargacontroller"
REFERER = "https://www.iberdrola.es/movilidad-electrica/puntos-de-recarga"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

# Charger type code -> human label. Confirmed against detail responses in
# Denia: `P` chargers are operated by "Iberdrola Clientes S.A.U" (the
# Iberdrola-owned network); `I` chargers are third-party / roaming partners
# (e.g. Spirii / PowerGo) surfaced through the same map. `R` and `N` appear
# in the UI's filter list but were not present in the sampled bbox; meaning
# unconfirmed.
CHARGE_POINT_TYPES = {"P": "iberdrola_own", "I": "roaming", "R": "R", "N": "N"}


@dataclass(frozen=True)
class BBox:
    """Geographic bounding box in WGS84 decimal degrees."""

    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    def as_payload(self) -> dict[str, float]:
        return {
            "latitudeMax": self.lat_max,
            "latitudeMin": self.lat_min,
            "longitudeMax": self.lon_max,
            "longitudeMin": self.lon_min,
        }


@dataclass
class Cluster:
    """Aggregated bucket returned by getGruposListarPuntosRecarga."""

    group_id: str
    latitude: float
    longitude: float
    socket_num: int
    available: int
    occupied: int
    reserved: int
    out_of_service: int
    not_operated: int
    under_construction: int
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Cluster":
        return cls(
            group_id=d["groupId"],
            latitude=d["latitude"],
            longitude=d["longitude"],
            socket_num=d["socketNum"],
            available=d["available"],
            occupied=d["occupied"],
            reserved=d["reserved"],
            out_of_service=d["outOfService"],
            not_operated=d["notOperated"],
            under_construction=d["underConstruction"],
            raw=d,
        )


@dataclass
class Charger:
    """Single charger from getListarPuntosRecarga (summary, no per-socket detail)."""

    cupr_id: int
    cp_id: int
    name: str
    latitude: float
    longitude: float
    type_code: str          # one of CHARGE_POINT_TYPES keys
    situation_code: str     # e.g. "OPER"
    status_code: str | None  # "AVAILABLE" / "OCCUPIED" / "OUT_OF_SERVICE"
    socket_num: int
    address: dict[str, Any]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Charger":
        loc = d["locationData"]
        cp_status = d.get("cpStatus") or {}
        return cls(
            cupr_id=loc["cuprId"],
            cp_id=d["cpId"],
            name=loc["cuprName"],
            latitude=loc["latitude"],
            longitude=loc["longitude"],
            type_code=loc["chargePointTypeCode"],
            situation_code=loc["situationCode"],
            status_code=cp_status.get("statusCode"),
            socket_num=d.get("socketNum", 0),
            address=(loc.get("supplyPointData") or {}).get("cpAddress") or {},
            raw=d,
        )


@dataclass
class Socket:
    """One connector on a charging pedestal (one physical socket within a
    logical socket). Sourced from `getDatosPuntoRecarga`."""

    logical_socket_id: int | None
    physical_socket_id: int | None
    physical_socket_code: str | None     # "1", "2", ... — per-pedestal index
    evse_id: str | None                  # CPO EVSE identifier (when assigned)
    socket_type: str | None              # "Mennekes", "Combo-Tipo2", "Chademo", "Tipo2-cable"
    socket_type_id: str | None           # numeric code, see module docstring
    max_power_kw: int | float | None
    price_per_kwh: float | None
    currency: str                        # always "EUR" in observed data
    status: str | None                   # AVAILABLE / OCCUPIED / OUT_OF_SERVICE / EV_CONNECTED
    raw_logical: dict[str, Any] = field(repr=False, default_factory=dict)
    raw_physical: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def is_free(self) -> bool:
        return self.status == "AVAILABLE"


@dataclass
class ChargerDetail:
    """Per-connector enrichment for one cuprId, from `getDatosPuntoRecarga`."""

    cupr_id: int
    name: str
    latitude: float
    longitude: float
    operator: str | None
    type_code: str                       # see CHARGE_POINT_TYPES
    address: dict[str, Any]
    rollup_status: str | None            # cpStatus.statusCode (may lag per-connector)
    sockets: list[Socket]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def free_count(self) -> int:
        return sum(1 for s in self.sockets if s.is_free)

    @property
    def socket_count(self) -> int:
        return len(self.sockets)

    @classmethod
    def from_json(cls, entry: dict[str, Any]) -> "ChargerDetail":
        loc = entry["locationData"]
        sockets: list[Socket] = []
        for ls in entry.get("logicalSocket") or []:
            ls_status = (ls.get("status") or {}).get("statusCode")
            for ps in ls.get("physicalSocket") or []:
                rate = (ps.get("appliedRate") or {}).get("recharge") or {}
                ps_status = (ps.get("status") or {}).get("statusCode")
                sockets.append(Socket(
                    logical_socket_id=ls.get("logicalSocketId"),
                    physical_socket_id=ps.get("physicalSocketId"),
                    physical_socket_code=ps.get("physicalSocketCode"),
                    evse_id=ls.get("evseId"),
                    socket_type=(ps.get("socketType") or {}).get("socketName"),
                    socket_type_id=(ps.get("socketType") or {}).get("socketTypeId"),
                    max_power_kw=ps.get("maxPower"),
                    price_per_kwh=rate.get("finalPrice"),
                    currency="EUR",
                    # The connector-level status lives on the *physical* socket
                    # when present, otherwise fall back to the logical socket.
                    status=ps_status or ls_status,
                    raw_logical=ls,
                    raw_physical=ps,
                ))
        return cls(
            cupr_id=loc["cuprId"],
            name=loc["cuprName"],
            latitude=loc["latitude"],
            longitude=loc["longitude"],
            operator=(loc.get("operator") or {}).get("operatorDesc"),
            type_code=loc["chargePointTypeCode"],
            address=(loc.get("supplyPointData") or {}).get("cpAddress") or {},
            rollup_status=(entry.get("cpStatus") or {}).get("statusCode"),
            sockets=sockets,
            raw=entry,
        )


class IberdrolaApiError(RuntimeError):
    """Raised when the API returns a non-2xx, an error envelope, or HTML."""


class IberdrolaEVClient:
    """Thin client for the Iberdrola charging-point public API.

    The Akamai edge rejects requests without browser-issued cookies.
    Provide either `cookie_header` (the raw `cookie:` value copied from a
    browser DevTools request) or `cookies` (a pre-built mapping or
    `requests.cookies.RequestsCookieJar`).
    """

    def __init__(
        self,
        *,
        cookie_header: str | None = None,
        cookies: dict[str, str] | None = None,
        language: str = "es",
        user_agent: str = DEFAULT_UA,
        session: requests.Session | None = None,
        timeout: float = 15.0,
    ) -> None:
        if not (cookie_header or cookies):
            raise ValueError(
                "Pass `cookie_header` (copied from a browser session on "
                "iberdrola.es) or `cookies=` — the Akamai edge blocks "
                "anonymous requests."
            )
        self._language = language
        self._timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update({
            "accept": "application/json, text/javascript, */*; q=0.01",
            "content-type": "application/json; charset=UTF-8",
            "origin": "https://www.iberdrola.es",
            "referer": REFERER,
            "user-agent": user_agent,
            "x-requested-with": "XMLHttpRequest",
        })
        if cookie_header:
            for name, value in _parse_cookie_header(cookie_header):
                self._session.cookies.set(name, value, domain=".iberdrola.es")
        if cookies:
            for name, value in cookies.items():
                self._session.cookies.set(name, value, domain=".iberdrola.es")

    # ----- public operations -------------------------------------------------

    def list_clusters(
        self,
        bbox: BBox,
        *,
        type_codes: Sequence[str] = ("P", "R", "I", "N"),
        socket_status: Sequence[str] = (),
        connectors_type: Sequence[str] = (),
        load_speed: Sequence[str] = (),
        advantageous: bool = False,
    ) -> list[Cluster]:
        """Aggregated clusters for zoomed-out map views."""

        dto = {
            "chargePointTypesCodes": list(type_codes),
            "socketStatus": list(socket_status),
            "advantageous": advantageous,
            "connectorsType": list(connectors_type),
            "loadSpeed": list(load_speed),
            **bbox.as_payload(),
        }
        entries = self._call("getGruposListarPuntosRecarga", dto)
        return [Cluster.from_json(e) for e in entries]

    def list_chargers(
        self,
        bbox: BBox,
        *,
        type_codes: Sequence[str] = ("P", "R", "I", "N"),
        socket_status: Sequence[str] = (),
        connectors_type: Sequence[str] = (),
        load_speed: Sequence[str] = (),
        advantageous: bool = False,
    ) -> list[Charger]:
        """Individual chargers inside `bbox` (summary form)."""

        dto = {
            "chargePointTypesCodes": list(type_codes),
            "socketStatus": list(socket_status),
            "advantageous": advantageous,
            "connectorsType": list(connectors_type),
            "loadSpeed": list(load_speed),
            **bbox.as_payload(),
        }
        entries = self._call("getListarPuntosRecarga", dto)
        return [Charger.from_json(e) for e in entries]

    def get_charger_details(self, cupr_ids: Iterable[int]) -> list[dict[str, Any]]:
        """Full per-socket detail (rates, max power, live status) for given IDs.

        The detail payload is deeply nested; this returns the raw `entidad`
        list. Use `ChargerDetail.from_json()` (or the higher-level `enrich()`)
        for a typed view.
        """

        dto = {"cuprId": [int(x) for x in cupr_ids]}
        return self._call("getDatosPuntoRecarga", dto)

    def enrich(
        self,
        chargers_or_ids: Iterable["Charger | int"],
        *,
        batch: int = 20,
    ) -> list[ChargerDetail]:
        """Fetch per-connector detail for a list of chargers (or cuprIds).

        Calls `getDatosPuntoRecarga` in batches of `batch` ids and returns
        typed `ChargerDetail` objects in the same order as the input. The
        server has been observed to accept at least 20 ids per call.
        """

        ids: list[int] = []
        for x in chargers_or_ids:
            ids.append(x.cupr_id if isinstance(x, Charger) else int(x))
        by_id: dict[int, ChargerDetail] = {}
        for i in range(0, len(ids), batch):
            for entry in self.get_charger_details(ids[i:i + batch]):
                detail = ChargerDetail.from_json(entry)
                by_id[detail.cupr_id] = detail
        return [by_id[i] for i in ids if i in by_id]

    # ----- low level ---------------------------------------------------------

    def _call(self, op: str, dto: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{BASE_URL}/{op}"
        body = json.dumps({"dto": dto, "language": self._language})
        resp = self._session.post(url, data=body, timeout=self._timeout)
        ctype = resp.headers.get("content-type", "")
        if resp.status_code != 200:
            raise IberdrolaApiError(
                f"{op} -> HTTP {resp.status_code} "
                f"({'Akamai bot wall — refresh browser cookies' if resp.status_code == 403 else ctype}): "
                f"{resp.text[:200]!r}"
            )
        if "application/json" not in ctype:
            raise IberdrolaApiError(
                f"{op}: expected JSON, got {ctype!r}; body starts with {resp.text[:120]!r}"
            )
        env = resp.json()
        if env.get("errorAjax") or env.get("serviceException"):
            raise IberdrolaApiError(
                f"{op}: server error: errorAjax={env.get('errorAjax')!r} "
                f"serviceException={env.get('serviceException')!r}"
            )
        return env.get("entidad") or []


# --- helpers -----------------------------------------------------------------


def _parse_cookie_header(header: str) -> list[tuple[str, str]]:
    """Parse a raw `cookie:` header value into (name, value) pairs."""

    pairs: list[tuple[str, str]] = []
    for chunk in header.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        pairs.append((name.strip(), value.strip()))
    return pairs


def parse_detail(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten one `getDatosPuntoRecarga` `entidad` entry to a plain dict.

    Convenience for ad-hoc JSON-dump callers; prefer `ChargerDetail.from_json()`
    for typed access.
    """

    detail = ChargerDetail.from_json(entry)
    return {
        "cupr_id": detail.cupr_id,
        "name": detail.name,
        "latitude": detail.latitude,
        "longitude": detail.longitude,
        "operator": detail.operator,
        "type_code": detail.type_code,
        "address": detail.address,
        "status": detail.rollup_status,
        "sockets": [
            {
                "evse_id": s.evse_id,
                "socket_type": s.socket_type,
                "socket_type_id": s.socket_type_id,
                "max_power_kw": s.max_power_kw,
                "price_per_kwh": s.price_per_kwh,
                "currency": s.currency,
                "status": s.status,
                "physical_socket_code": s.physical_socket_code,
            }
            for s in detail.sockets
        ],
    }


# --- example -----------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import os
    import sys

    p = argparse.ArgumentParser(description="Query Iberdrola EV charging-point API.")
    p.add_argument("--cookie-file", required=True,
                   help="File with the raw `cookie:` header copied from a logged browser session.")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"),
                   default=[38.687, 38.847, -0.122, 0.163],
                   help="Bounding box (default: small area near Denia/Alicante).")
    p.add_argument("--mode", choices=["list", "clusters", "detail"], default="list")
    p.add_argument("--ids", nargs="*", type=int, default=[],
                   help="cuprId values (used with --mode detail).")
    args = p.parse_args()

    if not os.path.exists(args.cookie_file):
        sys.exit(f"cookie file not found: {args.cookie_file}")
    with open(args.cookie_file) as f:
        cookie_header = f.read().strip()

    client = IberdrolaEVClient(cookie_header=cookie_header)
    bbox = BBox(args.bbox[0], args.bbox[1], args.bbox[2], args.bbox[3])

    if args.mode == "clusters":
        for c in client.list_clusters(bbox):
            print(f"{c.group_id:>10}  {c.latitude:.4f},{c.longitude:.4f}  "
                  f"{c.available}/{c.socket_num} free  occ={c.occupied}  oos={c.out_of_service}")
    elif args.mode == "list":
        for c in client.list_chargers(bbox):
            addr = c.address.get("streetName") or "?"
            print(f"{c.cupr_id:>8}  {c.type_code}  {c.status_code or '-':14}  "
                  f"{c.latitude:.4f},{c.longitude:.4f}  {c.name}  ({addr}, {c.address.get('townName','')})")
    else:
        if not args.ids:
            sys.exit("--mode detail requires --ids ID [ID...]")
        for entry in client.get_charger_details(args.ids):
            flat = parse_detail(entry)
            print(json.dumps(flat, indent=2, ensure_ascii=False))
