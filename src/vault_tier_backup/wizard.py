"""Interactive setup wizard (`vault-tier-backup init`).

Non-technical users shouldn't have to hand-edit JSON or run `setx` by hand. This
walks them through the essentials, writes a valid config.json, generates or
collects the backup password, and prints exactly what to do next.

The config-building logic (`build_config`) is a pure function of an answers dict
so it can be tested without any prompting; `run_wizard` does the I/O.
"""

import getpass
import json
import os
import secrets
import string
import subprocess
import sys

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DEFAULT_EXTENSIONS = [".xlsx", ".xlsm", ".accdb"]


def generate_password(length=24):
    """A strong, copy-pasteable password (no ambiguous punctuation)."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def build_config(answers):
    """Build a complete, valid config dict from an answers mapping. Every key
    run() may read is present with a sensible default, so the result never
    KeyErrors regardless of which optional features the user enabled."""
    email = answers.get("email")  # dict or None
    return {
        "paths": {
            "backup_source": answers["source"],
            "backup_root_exe": answers.get("backup_root_exe", "backup"),
            "backup_root_source": answers.get("backup_root_source", "BACKUP"),
        },
        "backup": {
            "extensions": answers.get("extensions", DEFAULT_EXTENSIONS),
            "include_subfolders_daily": True,
            "weekly_day": answers.get("weekly_day", 6),
            "weekly_full_backup": True,
            "dual_backup": answers.get("dual_backup", True),
            "max_age_days": answers.get("max_age_days", 1),
            "skip_keywords": answers.get("skip_keywords", ["- copy", "~$"]),
        },
        "control": {
            "dry_run": answers.get("dry_run", True),
            "email_enabled": email is not None,
            "upload_to_cloud": False,
            "cloud_platform": "onedrive",
            "delete_old_daily": True,
            "delete_old_weekly": True,
            "delete_old_monthly": True,
            "delete_old_yearly": True,
            "full_backup_mode": False,
            "verify_backups": True,
        },
        "retention": answers.get(
            "retention", {"daily_keep": 7, "weekly_keep": 5, "monthly_keep": 12, "yearly_keep": 2}
        ),
        "mirrors": answers.get("mirrors", []),
        "monitoring": {
            "alert_on_failure": True,
            "heartbeat_url": answers.get("heartbeat_url", ""),
            "max_quiet_hours": answers.get("max_quiet_hours", 26),
        },
        "email": {
            "method": (email or {}).get("method", "smtp"),
            "smtp_server": (email or {}).get("smtp_server", "smtp.office365.com"),
            "smtp_port": (email or {}).get("smtp_port", 587),
            "from": (email or {}).get("from", "you@example.com"),
            "to": (email or {}).get("to", "you@example.com"),
        },
        "cloud": {
            "onedrive": {
                "client_id": "YOUR_AZURE_APP_CLIENT_ID",
                "tenant_id": "YOUR_AZURE_TENANT_ID",
                "upload_path": "Documents/Backup",
            }
        },
    }


def _prompt(text, default=None):
    suffix = f" [{default}]" if default not in (None, "") else ""
    val = input(f"{text}{suffix}: ").strip()
    return val or (default if default is not None else "")


def _prompt_bool(text, default=False):
    hint = "Y/n" if default else "y/N"
    val = input(f"{text} [{hint}]: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


def _gather_answers():
    answers = {}

    while True:
        source = _prompt("Folder to back up (source)")
        if source and os.path.isdir(source):
            break
        print(f"  '{source}' is not an existing folder — try again.")
    answers["source"] = source

    exts = _prompt("File extensions to back up (comma-separated)", ",".join(DEFAULT_EXTENSIONS))
    answers["extensions"] = [e.strip() if e.strip().startswith(".") else "." + e.strip()
                             for e in exts.split(",") if e.strip()]

    for i, name in enumerate(WEEKDAYS):
        print(f"    {i} = {name}")
    while True:
        day = _prompt("Which day to roll dailies into a weekly?", "6")
        try:
            answers["weekly_day"] = int(day)
            break
        except ValueError:
            print("  Enter a number 0-6.")

    mirrors = _prompt(
        "Offsite mirror path(s) on ANOTHER drive/device (comma-separated, blank for none)", ""
    )
    answers["mirrors"] = [m.strip() for m in mirrors.split(",") if m.strip()]

    answers["heartbeat_url"] = _prompt(
        "Heartbeat URL for silent-failure alerts (e.g. a healthchecks.io URL, blank to skip)", ""
    )

    if _prompt_bool("Send email notifications?", default=False):
        method = "outlook" if _prompt_bool("Use desktop Outlook (else SMTP)?", default=False) else "smtp"
        email = {"method": method, "to": _prompt("Notify which email address?")}
        email["from"] = _prompt("Send from which address?", email["to"])
        if method == "smtp":
            email["smtp_server"] = _prompt("SMTP server", "smtp.office365.com")
            email["smtp_port"] = int(_prompt("SMTP port", "587"))
        answers["email"] = email

    # Leave dry_run on so the first run is a safe no-op the user can inspect.
    answers["dry_run"] = True
    return answers


def _handle_password():
    print("\n--- Backup password ---")
    if _prompt_bool("Generate a strong password automatically?", default=True):
        password = generate_password()
        print("\n  Your backup password (SAVE THIS NOW — a password manager is ideal):\n")
        print(f"      {password}\n")
        print("  If you lose it, every encrypted backup is permanently unrecoverable.")
    else:
        while True:
            password = getpass.getpass("  Enter backup password: ")
            if password and password == getpass.getpass("  Confirm password: "):
                break
            print("  Empty or mismatched — try again.")
    return password


def _apply_password_env(password):
    print("\nThe password is read from the BACKUP_ZIP_PASSWORD environment variable.")
    if os.name == "nt":
        if _prompt_bool("Set BACKUP_ZIP_PASSWORD in your Windows user environment now?", default=True):
            subprocess.run(["setx", "BACKUP_ZIP_PASSWORD", password], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("  Set. Open a NEW terminal for it to take effect.")
            return
        print('  Later, run:  setx BACKUP_ZIP_PASSWORD "<your-password>"')
    else:
        print("  Add to your shell profile:  export BACKUP_ZIP_PASSWORD='<your-password>'")


def run_wizard(config_path):
    print("=== vault-tier-backup setup ===\n")
    if os.path.exists(config_path):
        if not _prompt_bool(f"'{config_path}' already exists. Overwrite it?", default=False):
            print("Cancelled — existing config left untouched.")
            return 1

    answers = _gather_answers()
    config = build_config(answers)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"\nWrote {config_path}")

    password = _handle_password()
    _apply_password_env(password)

    print("\n--- Next steps ---")
    print(f"1. Review {config_path} (it starts in dry-run mode — nothing is written yet).")
    print("2. Test:  vault-tier-backup -c {0} backup   (dry run shows what WOULD happen)".format(config_path))
    print('3. When happy, set "dry_run": false in the config to run for real.')
    print("4. Schedule a daily run:  vault-tier-backup -c {0} install-schedule".format(config_path))
    if not answers["mirrors"]:
        print("5. Consider adding an offsite 'mirror' on another device — see the README (3-2-1).")
    return 0
