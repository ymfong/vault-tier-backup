"""Built-in scheduling.

Relying on the user to wire up Task Scheduler / cron by hand is the last
error-prone manual step in setup. `install-schedule` registers a daily job:

- Windows: writes a small launcher `.cmd` next to the config and registers a
  `schtasks` daily task that runs it. The task runs as the current user, so the
  `BACKUP_ZIP_PASSWORD` set in the user environment is visible to it.
- POSIX: writes a launcher `.sh` and prints a ready-to-paste crontab line (we
  don't edit the user's crontab for them).

The command/launcher/cron builders are pure functions so they can be tested
without touching the OS scheduler.
"""

import os
import stat
import subprocess
import sys

DEFAULT_TASK_NAME = "vault-tier-backup"
DEFAULT_TIME = "20:00"


def backup_command(config_path, python_exe=None):
    """The argv that a scheduled run should execute. Uses `python -m` so it
    doesn't depend on the console-script being on the scheduler's PATH."""
    python_exe = python_exe or sys.executable
    config_abs = os.path.abspath(config_path)
    return [python_exe, "-m", "vault_tier_backup.run", "-c", config_abs, "backup"]


def _quote(arg):
    return f'"{arg}"' if (" " in arg or "\\" in arg) else arg


def windows_launcher_content(config_path, python_exe=None):
    cmd = " ".join(_quote(a) for a in backup_command(config_path, python_exe))
    return f"@echo off\r\n{cmd}\r\n"


def posix_launcher_content(config_path, python_exe=None):
    cmd = " ".join(_quote(a) for a in backup_command(config_path, python_exe))
    return f"#!/bin/sh\n{cmd}\n"


def _parse_hhmm(time_str):
    hour, minute = time_str.split(":")
    hour, minute = int(hour), int(minute)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"Invalid time '{time_str}' (expected HH:MM, 24-hour).")
    return hour, minute


def cron_line(time_str, launcher_path):
    hour, minute = _parse_hhmm(time_str)
    return f"{minute} {hour} * * * {launcher_path}"


def _launcher_path(config_path, ext):
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), f"vault-tier-backup-run{ext}")


def install_windows(config_path, time_str, task_name, python_exe=None, runner=subprocess.run):
    _parse_hhmm(time_str)  # validate early
    launcher = _launcher_path(config_path, ".cmd")
    with open(launcher, "w", encoding="utf-8", newline="") as f:
        f.write(windows_launcher_content(config_path, python_exe))

    result = runner(
        ["schtasks", "/Create", "/TN", task_name, "/TR", _quote(launcher),
         "/SC", "DAILY", "/ST", time_str, "/F"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"schtasks failed: {result.stderr.strip() or result.stdout.strip()}")
    return (
        f"Scheduled daily backup '{task_name}' at {time_str}.\n"
        f"Launcher: {launcher}\n"
        f"Verify with:  schtasks /Query /TN \"{task_name}\"\n"
        f"Remove with:  vault-tier-backup uninstall-schedule"
    )


def install_posix(config_path, time_str, python_exe=None):
    launcher = _launcher_path(config_path, ".sh")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(posix_launcher_content(config_path, python_exe))
    os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    line = cron_line(time_str, launcher)
    return (
        f"Wrote launcher: {launcher}\n"
        f"Add this line to your crontab (run 'crontab -e'):\n\n    {line}\n"
    )


def install_schedule(config_path, time_str=DEFAULT_TIME, task_name=DEFAULT_TASK_NAME):
    if os.name == "nt":
        return install_windows(config_path, time_str, task_name)
    return install_posix(config_path, time_str)


def uninstall_schedule(task_name=DEFAULT_TASK_NAME, runner=subprocess.run):
    if os.name == "nt":
        result = runner(
            ["schtasks", "/Delete", "/TN", task_name, "/F"], capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"schtasks failed: {result.stderr.strip() or result.stdout.strip()}")
        return f"Removed scheduled task '{task_name}'."
    return (
        "On this platform, remove the cron entry yourself with 'crontab -e' "
        "(delete the vault-tier-backup line)."
    )
