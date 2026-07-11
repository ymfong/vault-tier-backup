"""Silent-failure monitoring.

The worst backup failure is the quiet one: the scheduled job stops running (the
machine was off, the task got disabled, the environment broke) and nobody finds
out until a restore emergency — by which point there's nothing to restore. Email
only fires on *successful* completion, so it can't catch a run that never
happened. "No news is bad news."

Two mechanisms address that:

- **Heartbeat (dead-man's-switch).** After a successful run the tool pings a URL
  you control (e.g. a healthchecks.io check, an Uptime Kuma monitor). That
  external service alerts YOU when the expected ping *doesn't* arrive — the only
  way to detect a run that never fired, because the detection lives off the
  machine. A failed run pings the same URL with a `/fail` suffix.
- **Staleness self-check.** At the start of each run the tool compares now
  against the last successful run and warns loudly if the gap is longer than
  expected — catching a silent gap the next time a run does happen.

Both are fail-safe: a monitoring error must never take down the backup itself.
"""

import logging
from datetime import datetime

import requests

from . import state

logger = logging.getLogger(__name__)


def check_staleness(backup_root_exe, max_quiet_hours):
    """Warn if too long has passed since the last successful run. Returns the
    number of hours since the last run (or None if unknown / disabled)."""
    if not max_quiet_hours:
        return None
    last = state.read_last_run_time(backup_root_exe)
    if last is None:
        return None  # first run ever — nothing to compare against
    hours = (datetime.now() - last).total_seconds() / 3600
    if hours > max_quiet_hours:
        logger.warning(
            "It has been %.1f hours since the last successful backup "
            "(expected at most %s). Scheduled runs may have been silently "
            "missed — check that the scheduler is enabled and the machine is on.",
            hours,
            max_quiet_hours,
        )
    return hours


def ping_heartbeat(heartbeat_url, suffix="", dry_run=False):
    """Ping the heartbeat URL (optionally with a suffix like '/fail'). Never
    raises — a monitoring failure must not fail the backup. Returns True on a
    successful ping."""
    if not heartbeat_url or dry_run:
        return False
    target = heartbeat_url.rstrip("/") + suffix
    try:
        requests.get(target, timeout=10)
        logger.info("Heartbeat pinged: %s", target)
        return True
    except requests.RequestException as e:
        logger.warning("Heartbeat ping failed (%s): %s", target, e)
        return False
