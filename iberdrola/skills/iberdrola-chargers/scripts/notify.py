"""Cross-platform local notification helper.

Always emits a terminal bell. Tries each available channel in order:
    macOS    -> osascript display notification
    Linux    -> notify-send (if installed) or paplay
    Windows  -> PowerShell BurntToast or msg

Does NOT send Telegram messages — those should be sent by Claude using
the telegram MCP tool, since the skill doesn't have credentials.

Usage:
    python notify.py --title "Charger free!" --message "Calle Mussola: 1/2 connectors AVAILABLE"
    python notify.py --title "..." --message "..." --no-beep   # skip terminal bell
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys


def beep(count: int = 3) -> None:
    """Emit BEL characters to the terminal. Multiple beeps are more attention-grabbing."""
    for _ in range(count):
        sys.stdout.write("\a")
        sys.stdout.flush()
    # Some terminals coalesce identical writes — small delay helps.
    import time
    time.sleep(0.05)


def notify_macos(title: str, message: str) -> bool:
    if not shutil.which("osascript"):
        return False
    # Escape double quotes in title/message for AppleScript literal strings.
    t = title.replace('"', '\\"')
    m = message.replace('"', '\\"')
    script = f'display notification "{m}" with title "{t}" sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
        return True
    except Exception:
        return False


def notify_linux(title: str, message: str) -> bool:
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", "--urgency=critical", title, message],
                check=False,
                timeout=5,
            )
            return True
        except Exception:
            pass
    return False


def notify_windows(title: str, message: str) -> bool:
    if not shutil.which("powershell.exe"):
        return False
    # Try BurntToast if installed; otherwise fall back to msgbox.
    burnt = (
        f'if (Get-Module -ListAvailable -Name BurntToast) {{'
        f'  New-BurntToastNotification -Text "{title}", "{message}"'
        f'}} else {{'
        f'  [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null;'
        f'  [System.Windows.Forms.MessageBox]::Show("{message}", "{title}") | Out-Null'
        f'}}'
    )
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", burnt],
            check=False,
            timeout=8,
        )
        return True
    except Exception:
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--message", required=True)
    p.add_argument("--no-beep", action="store_true")
    p.add_argument("--beep-count", type=int, default=3)
    args = p.parse_args()

    if not args.no_beep:
        beep(args.beep_count)

    # Print to stderr so it's visible even if stdout is being captured.
    print(f"[notify] {args.title} — {args.message}", file=sys.stderr)

    system = platform.system()
    delivered = False
    if system == "Darwin":
        delivered = notify_macos(args.title, args.message)
    elif system == "Linux":
        delivered = notify_linux(args.title, args.message)
    elif system == "Windows":
        delivered = notify_windows(args.title, args.message)

    if delivered:
        print(f"[notify] desktop notification sent via {system}", file=sys.stderr)
    else:
        print(f"[notify] no desktop notification channel available on {system}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
