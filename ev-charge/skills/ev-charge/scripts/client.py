"""Build a ready-to-use IberdrolaEVClient with HTTP-harvested Akamai cookies.

The Iberdrola API sits behind Akamai Bot Manager and rejects anonymous
requests with HTTP 403. Akamai only checks for cookie *presence*, not
sensor-validated values — so a single requests.get() to the public map
page with browser-like headers gets us cookies the API will accept.

No headless browser, no manual cookie copy-paste.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

# Make the bundled iberdrola_evcp.py importable when this script is run
# from the skill's scripts/ directory.
sys.path.insert(0, str(Path(__file__).parent))

from iberdrola_evcp import IberdrolaEVClient  # noqa: E402


BOOTSTRAP_URL = "https://www.iberdrola.es/movilidad-electrica/puntos-de-recarga"
BROWSER_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    ),
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}
REQUIRED_COOKIES = ("_abck", "bm_sz", "ak_bmsc")


def harvest_cookies(timeout: float = 15.0) -> dict[str, str]:
    """Single HTTP GET → Set-Cookie response → dict of cookies."""

    with requests.Session() as s:
        s.headers.update(BROWSER_HEADERS)
        resp = s.get(BOOTSTRAP_URL, timeout=timeout, allow_redirects=True)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Bootstrap GET returned HTTP {resp.status_code}; "
            f"Akamai may have tightened"
        )
    cookies = {
        c.name: c.value
        for c in resp.cookies
        if not c.domain or "iberdrola.es" in c.domain
    }
    missing = [c for c in REQUIRED_COOKIES if c not in cookies]
    if missing:
        raise RuntimeError(
            f"Cookies present but {missing} missing. "
            f"Got: {sorted(cookies)}"
        )
    return cookies


def make_client(timeout: float = 15.0) -> IberdrolaEVClient:
    """Convenience: harvest + return a configured client."""

    cookies = harvest_cookies(timeout=timeout)
    return IberdrolaEVClient(cookies=cookies)
