import os
from datetime import datetime


def determine_backup_type(today, weekly_day):
    """"weekly" on the configured weekly day, "daily" otherwise."""
    return "weekly" if today.weekday() == weekly_day else "daily"


def determine_days_limit(backup_type, weekly_full_backup, backup_root_exe, max_age_days):
    """None means "no age filter" (full backup). Must be called with the
    already-determined backup_type, not a value that's about to change."""
    if backup_type == "weekly" and weekly_full_backup:
        return None
    return get_days_limit(backup_root_exe, max_age_days)


def get_state_file(backup_root_exe):
    return os.path.join(backup_root_exe, ".last_backup_time")


def get_days_limit(backup_root_exe, default_days=1):
    state_file = get_state_file(backup_root_exe)

    if not os.path.exists(state_file):
        return default_days

    try:
        with open(state_file, "r") as f:
            last_run = datetime.fromisoformat(f.read().strip())
    except Exception:
        return default_days

    delta = datetime.now() - last_run
    return delta.total_seconds() / 86400  # float days


def read_last_run_time(backup_root_exe):
    """Return the datetime of the last successful run, or None if unknown."""
    state_file = get_state_file(backup_root_exe)
    if not os.path.exists(state_file):
        return None
    try:
        with open(state_file, "r") as f:
            return datetime.fromisoformat(f.read().strip())
    except Exception:
        return None


def save_last_run_time(backup_root_exe, timestamp=None):
    state_file = get_state_file(backup_root_exe)
    if timestamp is None:
        timestamp = datetime.now()
    os.makedirs(backup_root_exe, exist_ok=True)
    with open(state_file, "w") as f:
        f.write(timestamp.isoformat())
