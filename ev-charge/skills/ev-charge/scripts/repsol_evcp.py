"""Low-level direct client for Repsol's public Waylet RMVE API.

Unauthenticated, returns LIVE per-connector status. Two endpoints:

    POST https://pro.waylet.es/api/public/rmve/commerces  {"lat","lng"}
        -> array of nearest commerce(s): {_id, name, address}
    GET  https://pro.waylet.es/api/public/rmve/commerces/{_id}
        -> station detail: connectors grouped FAST/ULTRA/REGULAR, each with a
           real-time `status` (AVAILABLE / BUSY / CHARGING / INOPERATIVE).

No login, no cookie, no API key — just browser-like headers. This is the same
data the Waylet "scan-and-charge" web flow uses. Treat it as undocumented:
rate-limit politely. Returns raw dicts; mapping to a normalized model lives in
`providers.py`.
"""

from __future__ import annotations

import time

import requests


API_BASE = "https://pro.waylet.es/api/public/rmve/commerces"
REFERER = "https://movilidadelectrica.waylet.es/"
# Repsol's static station finder — lists every Spanish EV station WITH
# coordinates (but no live status). Used to discover stations in a bbox; live
# status then comes from the Waylet detail endpoint above.
SEARCH_URL = (
    "https://www.repsol.es/bin/repsol/searchmiddleware/"
    "station-search.json?action=search&idioma=es&tipo=3"
)
SEARCH_REFERER = (
    "https://www.repsol.es/particulares/vehiculos/estaciones-de-servicio/"
    "servicios/recarga-electrica/"
)
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
_DEG_PER_KM_LAT = 1.0 / 111.0


class RepsolApiError(RuntimeError):
    """The Waylet RMVE API returned an error or unparseable response."""


class RepsolAuthError(RepsolApiError):
    """Blocked / rate-limited (HTTP 401/403/429)."""


class RepsolClient:
    """Thin HTTP client for the public Waylet RMVE endpoints."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        spacing_s: float = 0.12,
        user_agent: str = DEFAULT_UA,
    ) -> None:
        self._timeout = timeout
        self._spacing = spacing_s
        self._session = requests.Session()
        self._session.headers.update({
            "user-agent": user_agent,
            "accept": "application/json, text/plain, */*",
            "origin": "https://movilidadelectrica.waylet.es",
            "referer": REFERER,
        })

    def _pace(self) -> None:
        if self._spacing:
            time.sleep(self._spacing)

    @staticmethod
    def _check_auth(resp: requests.Response) -> None:
        # Auth/rate-limit responses often carry an EMPTY body; check status
        # BEFORE any empty-body short-circuit so they aren't mistaken for
        # "no data".
        if resp.status_code in (401, 403, 429):
            raise RepsolAuthError(f"Waylet API HTTP {resp.status_code} (blocked or rate-limited)")

    def nearest(self, lat: float, lng: float) -> list[dict]:
        """Return the nearest commerce(s) to a point (closest 1-2)."""
        self._pace()
        try:
            resp = self._session.post(
                API_BASE, json={"lat": lat, "lng": lng}, timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise RepsolApiError(f"nearest lookup failed: {exc}") from exc
        self._check_auth(resp)
        if resp.status_code == 204:
            return []
        if resp.status_code != 200:
            raise RepsolApiError(f"nearest lookup HTTP {resp.status_code}")
        if not resp.content:
            return []
        data = resp.json()
        return data if isinstance(data, list) else []

    def detail(self, commerce_id: str) -> dict | None:
        """Return full station detail (incl. live connector status), or None."""
        self._pace()
        url = f"{API_BASE}/{commerce_id}"
        try:
            resp = self._session.get(url, timeout=self._timeout)
        except requests.RequestException as exc:
            raise RepsolApiError(f"detail {commerce_id} failed: {exc}") from exc
        self._check_auth(resp)
        if resp.status_code == 204:
            return None
        if resp.status_code != 200:
            raise RepsolApiError(f"detail {commerce_id} HTTP {resp.status_code}")
        if not resp.content:
            return None
        return resp.json()

    def search_bbox(self, bbox: tuple[float, float, float, float]) -> list[dict]:
        """Return static station-finder entries whose coords fall in the bbox.

        One POST to station-search.json (lists all Spanish EV stations). Each
        entry has `x`(lon), `y`(lat), `nombre`, `id`, `velocidad` — but NO live
        status. bbox = (lat_min, lat_max, lon_min, lon_max).
        """
        lat_min, lat_max, lon_min, lon_max = bbox
        try:
            resp = self._session.post(
                SEARCH_URL,
                headers={
                    "x-requested-with": "XMLHttpRequest",
                    "referer": SEARCH_REFERER,
                    "origin": "https://www.repsol.es",
                },
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise RepsolApiError(f"station-search failed: {exc}") from exc
        self._check_auth(resp)
        if resp.status_code != 200 or not resp.content:
            raise RepsolApiError(f"station-search HTTP {resp.status_code}")
        items = (resp.json().get("recarga") or {}).get("items") or []
        out = []
        for it in items:
            x, y = it.get("x"), it.get("y")
            if x is None or y is None:
                continue
            if lat_min <= y <= lat_max and lon_min <= x <= lon_max:
                out.append(it)
        return out

    def discover(
        self, bbox: tuple[float, float, float, float]
    ) -> dict[str, tuple[float, float]]:
        """Find Waylet commerce ids for the stations inside a bbox.

        Uses station-search to get in-bbox station coordinates, then probes the
        Waylet nearest endpoint at each station's exact location (where it
        reliably resolves) to recover the live-status commerce id. Returns
        {commerce_id: (lat, lon)} with real coordinates from station-search.
        """
        found: dict[str, tuple[float, float]] = {}
        for st in self.search_bbox(bbox):
            lat, lng = st["y"], st["x"]
            for entry in self.nearest(lat, lng):
                sid = entry.get("_id")
                if sid and sid not in found:
                    found[sid] = (lat, lng)
        return found
