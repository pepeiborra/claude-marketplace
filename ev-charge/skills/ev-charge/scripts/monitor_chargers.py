"""Register and check server-side charger watches (BACKEND-ONLY).

The watch subsystem lives in the monitor backend: you register a set of
chargers, the backend's background poller fetches their live status every cycle,
and a busy->free transition fires a notification (terminal/desktop/Telegram/web
push, depending on how the server is wired). Unlike find_chargers/charger_status
this has NO direct-client fallback — there is no skill-local poller — so if the
backend is unreachable it FAILS with a clear "needs the backend" message.

Typical flow:
    search (find_chargers) -> everything busy ->
    monitor_chargers.py register iberdrola:6760 repsol:5f80...   # POST /api/watch
    ... later ...
    monitor_chargers.py list                                     # GET /api/watches
    monitor_chargers.py unregister iberdrola:6760                # DELETE /api/watch

Ids are GLOBAL ("<provider>:<native>"), e.g. iberdrola:6760. As a convenience
you may pass bare native ids together with --provider to build the global id:
    monitor_chargers.py register --provider iberdrola 6760 6761

Backend base URL: $EV_CHARGE_BACKEND, else http://pipi.local:8765.

Exit codes:
    0  ok
    1  backend unavailable / needs the backend
    2  all ids rejected (none watchable)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import backend  # noqa: E402


_BACKEND_HINT = (
    "The charger monitor needs the backend server (the watch/poll subsystem has "
    "no standalone fallback). Start it (e.g. `python -m server` in "
    "~/scratch/iberdrola, or run it on the Pi) and/or set EV_CHARGE_BACKEND to "
    "its URL, then retry. For a one-off check without the backend, use "
    "charger_status.py instead (it falls back to the direct client)."
)


def _to_global_ids(raw_ids: list[str], provider: str | None) -> list[str]:
    """Build global ids. Bare native ids require --provider to qualify them."""
    out: list[str] = []
    for i in raw_ids:
        i = i.strip()
        if not i:
            continue
        if ":" in i:
            out.append(i)
        elif provider:
            out.append(f"{provider}:{i}")
        else:
            raise SystemExit(
                f"id {i!r} is not a global id and no --provider given; "
                f"pass iberdrola:{i} or add --provider iberdrola"
            )
    return out


def _fail_no_backend(exc: Exception) -> int:
    print(f"ERROR: backend unavailable ({exc}).", file=sys.stderr)
    print(_BACKEND_HINT, file=sys.stderr)
    return 1


def cmd_register(args) -> int:
    ids = _to_global_ids(args.ids, args.provider)
    if not ids:
        print("ERROR: no ids given", file=sys.stderr)
        return 2
    try:
        result = backend.watch(ids=ids, ttl_s=args.ttl_s)
    except backend.BackendUnavailable as exc:
        return _fail_no_backend(exc)

    watched = result.get("watched") or []
    rejected = result.get("rejected") or []
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"Registered {len(watched)} watch(es) on backend {backend.base_url()}:")
        for gid in watched:
            print(f"  + {gid}")
        for r in rejected:
            print(f"  x {r.get('id')}: {r.get('reason')}", file=sys.stderr)
    if not watched:
        print("WARN: nothing registered (all ids rejected)", file=sys.stderr)
        return 2
    return 0


def cmd_list(args) -> int:
    try:
        result = backend.watches()
    except backend.BackendUnavailable as exc:
        return _fail_no_backend(exc)

    entries = result.get("watches") or []
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if not entries:
        print(f"No active watches on backend {backend.base_url()}.")
        return 0

    print(f"{len(entries)} active watch(es) on backend {backend.base_url()}:\n")
    freed = []
    for e in entries:
        free = e.get("free_connectors")
        total = e.get("total_connectors")
        status = e.get("status")
        polled = e.get("polled")
        expires = e.get("expires_in_s")
        if not polled:
            counts = "not yet polled"
        else:
            counts = f"{free}/{total} free"
            if isinstance(free, int) and free > 0:
                freed.append(e)
        name = e.get("name") or e.get("charger_id")
        print(
            f"  {e.get('charger_id'):<28} {counts:<16} "
            f"status={status or '-':<14} expires_in={expires}s  {name}"
        )
    if freed:
        print("\nFREED UP:")
        for e in freed:
            print(
                f"  * {e.get('charger_id')} — {e.get('free_connectors')}/"
                f"{e.get('total_connectors')} AVAILABLE  ({e.get('name')})"
            )
    return 0


def cmd_unregister(args) -> int:
    ids = _to_global_ids(args.ids, args.provider)
    if not ids:
        print("ERROR: no ids given", file=sys.stderr)
        return 2
    try:
        result = backend.unwatch(ids=ids)
    except backend.BackendUnavailable as exc:
        return _fail_no_backend(exc)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        removed = result.get("removed") or []
        print(f"Removed {len(removed)} watch(es): {removed}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Server-side charger watch (backend-only).")
    p.add_argument("--json", action="store_true", help="Emit raw JSON.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("register", help="POST /api/watch — start watching ids.")
    pr.add_argument("ids", nargs="+", help="Global ids (provider:native) or bare native ids.")
    pr.add_argument("--provider", default=None, help="Qualify bare native ids.")
    pr.add_argument("--ttl-s", type=int, default=None, dest="ttl_s",
                    help="Watch lifetime in seconds (backend clamps).")
    pr.set_defaults(func=cmd_register)

    pl = sub.add_parser("list", help="GET /api/watches — show watches + which freed up.")
    pl.set_defaults(func=cmd_list)

    pu = sub.add_parser("unregister", help="DELETE /api/watch — stop watching ids.")
    pu.add_argument("ids", nargs="+", help="Global ids (provider:native) or bare native ids.")
    pu.add_argument("--provider", default=None, help="Qualify bare native ids.")
    pu.set_defaults(func=cmd_unregister)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
