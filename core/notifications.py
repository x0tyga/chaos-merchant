"""
Desktop Notification Utility
macOS (osascript) primary, Linux (notify-send) fallback, silent no-op if
neither mechanism is available (e.g. a headless server) - a notification
failure should never break a pipeline or scheduled job.

Every call is ALSO logged to NOTIFICATION_LOG_PATH (data/notification_log.json)
regardless of whether the desktop notification actually got delivered -
this is what makes a notification durable: an osascript/notify-send popup
disappears if the machine is asleep, locked, or nobody's looking at the
screen right that second, so it can't be the only record that something
happened. The log entry is the source of truth; the desktop popup is a
best-effort nice-to-have on top of it.
"""

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_LOGGED_NOTIFICATIONS = 1000


def _notification_log_path() -> Path:
    return Path(os.getenv('DATA_DIR', './data')) / 'notification_log.json'


def _log_notification(title: str, message: str, delivered: bool) -> None:
    """Records every notification that fired, delivered or not - never raises (logging must not break the caller)."""
    try:
        path = _notification_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        entries = []
        if path.exists():
            try:
                with open(path, 'r') as f:
                    entries = json.load(f)
            except Exception:
                entries = []

        entries.append({
            'timestamp': datetime.now().isoformat(),
            'title': title,
            'message': message,
            'delivered': delivered
        })
        entries = entries[-MAX_LOGGED_NOTIFICATIONS:]

        with open(path, 'w') as f:
            json.dump(entries, f, indent=2)
    except Exception as e:
        logger.debug(f"Notification logging skipped (non-fatal): {e}")


def send_notification(title: str, message: str) -> bool:
    """
    Send a desktop notification and unconditionally log it to
    data/notification_log.json (see module docstring for why the log,
    not the popup, is the durable record).

    Gated by ENABLE_NOTIFICATIONS env var (default: enabled) for the
    DESKTOP POPUP only - the log entry is still written even when
    notifications are disabled or no delivery mechanism exists, so
    disabling desktop popups can never make something "silently missed."

    Returns:
        True if a notification was actually sent, False if notifications
        are disabled or no supported mechanism exists on this machine.
        Never raises.
    """
    if os.getenv('ENABLE_NOTIFICATIONS', 'true').strip().lower() not in ('true', '1', 'yes'):
        _log_notification(title, message, delivered=False)
        return False

    try:
        if shutil.which('osascript'):  # macOS
            script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
            subprocess.run(['osascript', '-e', script], check=True, capture_output=True, timeout=5)
            _log_notification(title, message, delivered=True)
            return True
        elif shutil.which('notify-send'):  # Linux
            subprocess.run(['notify-send', title, message], check=True, capture_output=True, timeout=5)
            _log_notification(title, message, delivered=True)
            return True
        else:
            logger.info(f"ℹ No desktop notification mechanism available - would have sent: [{title}] {message}")
            _log_notification(title, message, delivered=False)
            return False
    except Exception as e:
        logger.warning(f"⚠ Failed to send desktop notification: {e}")
        _log_notification(title, message, delivered=False)
        return False
