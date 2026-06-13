"""Thin HTTP client for the ev-charge backend monitor server.

The skill PREFERS this backend (it adds history, multi-provider fan-out, live
status from networks the direct clients don't speak, and the watch subsystem)
but every read-only call has a direct-client fallback so the skill still works
standalone when no backend is reachable.

Base URL resolution:
    1. $EV_CHARGE_BACKEND if set (e.g. http://127.0.0.1:8812)
    2. http://pipi.local:8765  (the Pi default)

Everything here has a tight timeout so a missing/slow backend degrades quickly
to the fallback path instead of hanging the skill. `BackendUnavailable` is the
signal callers use to decide "fall back to the direct client".
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "http://pipi.local:8765"

# Connect + read budget for a single backend call. Short on purpose: a backend
# that is down (connection refused) fails instantly; one that is merely slow or
# unreachable (wrong host, no route) must not hang the skill, so we cap it.
DEFAULT_TIMEOUT_S = 8.0


class BackendUnavailable(Exception):
    """The backend could not be reached or returned a transport-level failure.

    Raised on connection-refused, DNS failure, timeout, or a non-2xx HTTP
    status. Callers treat this as the trigger to fall back to the direct
    client (for read-only search/status) or to fail with a clear message (for
    the backend-only watch subsystem).
    """


def base_url() -> str:
    """Resolve the backend base URL (env override, else the Pi default)."""
    return (os.environ.get("EV_CHARGE_BACKEND") or DEFAULT_BASE_URL).rstrip("/")


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Any:
    """Make one HTTP call to the backend; return the decoded JSON.

    Raises ``BackendUnavailable`` on any transport failure or non-2xx status so
    the caller can fall back. Uses only the stdlib (urllib) — no dependency on
    `requests`, so the backend path works even before the direct clients' deps
    are installed.
    """
    url = base_url() + path
    if params:
        # Drop None values so optional query params are omitted cleanly.
        clean = {k: v for k, v in params.items() if v is not None}
        url = url + "?" + urllib.parse.urlencode(clean)

    data: bytes | None = None
    headers = {"accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        # A 4xx/5xx with a JSON body is still a "backend reached" outcome for
        # some endpoints (e.g. 422 invalid query). But for the fallback
        # decision we treat any non-2xx as unavailable EXCEPT where the caller
        # explicitly wants the body — those callers catch HTTPError themselves.
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise BackendUnavailable(
            f"backend HTTP {exc.code} for {method} {path}"
            + (f": {detail}" if detail else "")
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # URLError wraps connection-refused / DNS failure; TimeoutError is the
        # read/connect timeout; OSError covers lower-level socket errors.
        reason = getattr(exc, "reason", exc)
        raise BackendUnavailable(
            f"backend unreachable at {base_url()} ({reason})"
        ) from exc

    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError) as exc:
        raise BackendUnavailable(f"backend returned non-JSON for {path}") from exc


# --- read-only endpoints (have a direct-client fallback) --------------------


def search(
    *,
    provider: str,
    center: tuple[float, float] | None = None,
    radius_km: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """GET /api/search. Returns {"chargers":[...], "errors":[...]}.

    Supply either center+radius_km or bbox.
    """
    params: dict[str, Any] = {"provider": provider}
    if bbox is not None:
        params["bbox"] = ",".join(str(x) for x in bbox)
    elif center is not None:
        params["center"] = f"{center[0]},{center[1]}"
        params["radius_km"] = radius_km
    else:
        raise ValueError("search() needs center+radius_km or bbox")
    return _request("GET", "/api/search", params=params, timeout=timeout)


def charger(*, provider: str, ids: list[str], timeout: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """GET /api/charger. Returns {"chargers":[...], "errors"?:[...]}."""
    return _request(
        "GET",
        "/api/charger",
        params={"provider": provider, "ids": ",".join(str(i) for i in ids)},
        timeout=timeout,
    )


def providers(*, timeout: float = DEFAULT_TIMEOUT_S) -> list[dict[str, Any]]:
    """GET /api/providers -> [{key, display_name, supports_live_status}]."""
    return _request("GET", "/api/providers", timeout=timeout)


# --- watch subsystem (BACKEND-ONLY, no direct fallback) ---------------------


def watch(*, ids: list[str], ttl_s: int | None = None, timeout: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """POST /api/watch -> {watched:[...], rejected:[{id,reason}]}."""
    body: dict[str, Any] = {"ids": ids}
    if ttl_s is not None:
        body["ttl_s"] = ttl_s
    return _request("POST", "/api/watch", body=body, timeout=timeout)


def watches(*, timeout: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """GET /api/watches -> {watches:[...]}."""
    return _request("GET", "/api/watches", timeout=timeout)


def unwatch(*, ids: list[str], timeout: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """DELETE /api/watch?ids=... -> {removed:[...]}."""
    return _request(
        "DELETE",
        "/api/watch",
        params={"ids": ",".join(str(i) for i in ids)},
        timeout=timeout,
    )


# --- shape adapter ----------------------------------------------------------


def charger_dict_to_row(d: dict[str, Any]) -> dict[str, Any]:
    """Map a backend ``charger_dict`` into the skill's find_chargers row shape.

    The backend's charger_id is a GLOBAL id ("provider:native"); the skill's
    direct-client rows use the native id. We keep the GLOBAL id as charger_id
    (it's what the watch subsystem wants) but the values otherwise line up with
    the direct-client rows, so the human-readable table renders identically.
    """
    connectors = d.get("connectors") or []
    prices = [c.get("price_per_kwh") for c in connectors if c.get("price_per_kwh") is not None]
    min_price = min(prices) if prices else d.get("price_per_kwh")
    free = sum(1 for c in connectors if (c.get("status") or "") == "AVAILABLE")
    return {
        "provider": d.get("provider"),
        "charger_id": d.get("charger_id"),
        "name": d.get("name") or "",
        "address": d.get("address") or "",
        "free": free,
        "total": len(connectors),
        "max_kw": d.get("max_power_kw"),
        "min_price_eur_per_kwh": min_price,
        "distance_km": None,  # filled in by the caller using lat/lon
        "approx": False,
        "latitude": d.get("latitude"),
        "longitude": d.get("longitude"),
        "operator": d.get("operator"),
    }


def charger_dict_to_status(d: dict[str, Any]) -> dict[str, Any]:
    """Map a backend ``charger_dict`` into the skill's charger_status row shape."""
    connectors = d.get("connectors") or []
    OUT_OF_SERVICE = {"OUT_OF_SERVICE", "NOT_OPERATED", "UNDER_CONSTRUCTION"}
    statuses = [(c.get("status") or "") for c in connectors]
    all_oos = bool(statuses) and all(s in OUT_OF_SERVICE for s in statuses)
    free = sum(1 for s in statuses if s == "AVAILABLE")
    return {
        "provider": d.get("provider"),
        "charger_id": d.get("charger_id"),
        "name": d.get("name") or "",
        "free": free,
        "total": len(connectors),
        "all_out_of_service": all_oos,
        "address": d.get("address") or "",
        "connectors": [
            {
                "code": c.get("code"),
                "type": c.get("type"),
                "status": c.get("status"),
                "max_kw": c.get("max_power_kw"),
                "price_eur_per_kwh": c.get("price_per_kwh"),
            }
            for c in connectors
        ],
    }
