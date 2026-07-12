"""Built-in scheduling.

Relying on the user to wire up Task Scheduler / cron by hand is the last
error-prone manual step in setup. `install-schedule` registers a daily job:

- Windows: writes a small launcher `.cmd` next to the config and registers the
  task from an XML definition so a missed run (PC off, asleep, or logged out at
  the scheduled time) catches up at the next opportunity instead of being lost.
  The task runs as the current user, so the `BACKUP_ZIP_PASSWORD` set in the
  user environment is visible to it.
- POSIX: writes a launcher `.sh` and prints a ready-to-paste crontab line (we
  don't edit the user's crontab for them).

The command/launcher/cron/XML builders are pure functions so they can be tested
without touching the OS scheduler.
"""

import os
import stat
import subprocess
import sys
import tempfile
from datetime import datetime

DEFAULT_TASK_NAME = "vault-tier-backup"
DEFAULT_TIME = "20:00"


def backup_command(config_path, python_exe=None):
    """The argv that a scheduled run should execute. Uses `python -m` so it
    doesn't depend on the console-script being on the scheduler's PATH. In a
    frozen (PyInstaller) build there is no interpreter to hand `-m` — the exe
    itself takes the CLI arguments directly."""
    config_abs = os.path.abspath(config_path)
    if python_exe is None and getattr(sys, "frozen", False):
        return [sys.executable, "-c", config_abs, "backup"]
    python_exe = python_exe or sys.executable
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


def _xml_escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def windows_task_xml(launcher_path, time_str, description="vault-tier-backup daily backup"):
    """Task Scheduler XML for a daily run that survives the PC being off/asleep/
    logged-out at the scheduled time.

    StartWhenAvailable makes a missed run fire at the next opportunity (next
    logon / wake) instead of being silently skipped; WakeToRun wakes the machine
    from sleep to run. The task runs under InteractiveToken (the current user) so
    the per-user BACKUP_ZIP_PASSWORD env var is visible — which is why we don't
    use the SYSTEM account or a stored Windows password."""
    hour, minute = _parse_hhmm(time_str)
    start = datetime.now().strftime("%Y-%m-%d") + f"T{hour:02d}:{minute:02d}:00"
    launcher_path = _xml_escape(launcher_path)
    description = _xml_escape(description)
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\r\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\r\n'
        "  <RegistrationInfo>\r\n"
        f"    <Description>{description}</Description>\r\n"
        "  </RegistrationInfo>\r\n"
        "  <Triggers>\r\n"
        "    <CalendarTrigger>\r\n"
        f"      <StartBoundary>{start}</StartBoundary>\r\n"
        "      <Enabled>true</Enabled>\r\n"
        "      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>\r\n"
        "    </CalendarTrigger>\r\n"
        "  </Triggers>\r\n"
        "  <Principals>\r\n"
        '    <Principal id="Author">\r\n'
        "      <LogonType>InteractiveToken</LogonType>\r\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\r\n"
        "    </Principal>\r\n"
        "  </Principals>\r\n"
        "  <Settings>\r\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\r\n"
        "    <WakeToRun>true</WakeToRun>\r\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\r\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\r\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\r\n"
        "    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>\r\n"
        "    <Enabled>true</Enabled>\r\n"
        "  </Settings>\r\n"
        '  <Actions Context="Author">\r\n'
        f"    <Exec><Command>{launcher_path}</Command></Exec>\r\n"
        "  </Actions>\r\n"
        "</Task>\r\n"
    )


def install_windows(config_path, time_str, task_name, python_exe=None, runner=subprocess.run):
    _parse_hhmm(time_str)  # validate early
    launcher = _launcher_path(config_path, ".cmd")
    with open(launcher, "w", encoding="utf-8", newline="") as f:
        f.write(windows_launcher_content(config_path, python_exe))

    xml = windows_task_xml(launcher, time_str)
    xml_fd, xml_path = tempfile.mkstemp(suffix=".xml", prefix="vtb-task-")
    os.close(xml_fd)
    try:
        with open(xml_path, "w", encoding="utf-16") as f:  # schtasks /XML expects Unicode
            f.write(xml)
        result = runner(
            ["schtasks", "/Create", "/TN", task_name, "/XML", xml_path, "/F"],
            capture_output=True, text=True,
        )
    finally:
        try:
            os.remove(xml_path)
        except OSError:
            pass

    if result.returncode != 0:
        raise RuntimeError(f"schtasks failed: {result.stderr.strip() or result.stdout.strip()}")
    return (
        f"Scheduled daily backup '{task_name}' at {time_str}.\n"
        f"Missed runs (PC off/asleep/logged out) catch up at the next opportunity.\n"
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
