"""
Desktop Notification Utility
macOS (osascript) primary, Linux (notify-send) fallback, silent no-op if
neither mechanism is available (e.g. a headless server) - a notification
failure should never break a pipeline or scheduled job.
"""

import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


def send_notification(title: str, message: str) -> bool:
    """
    Send a desktop notification.

    Gated by ENABLE_NOTIFICATIONS env var (default: enabled).

    Returns:
        True if a notification was actually sent, False if notifications
        are disabled or no supported mechanism exists on this machine.
        Never raises.
    """
    if os.getenv('ENABLE_NOTIFICATIONS', 'true').strip().lower() not in ('true', '1', 'yes'):
        return False

    try:
        if shutil.which('osascript'):  # macOS
            script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
            subprocess.run(['osascript', '-e', script], check=True, capture_output=True, timeout=5)
            return True
        elif shutil.which('notify-send'):  # Linux
            subprocess.run(['notify-send', title, message], check=True, capture_output=True, timeout=5)
            return True
        else:
            logger.info(f"ℹ No desktop notification mechanism available - would have sent: [{title}] {message}")
            return False
    except Exception as e:
        logger.warning(f"⚠ Failed to send desktop notification: {e}")
        return False
