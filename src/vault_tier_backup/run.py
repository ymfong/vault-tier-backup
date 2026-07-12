"""Orchestrates a single daily/weekly/monthly/yearly backup run."""

import argparse
import json as _json
import logging
import os
import sys
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from . import archive, cloud, collector, keyguard, mirror, monitor, notify, restore, safety, schedule, state, wizard
from .config import get_required_env, load_config


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "time": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return _json.dumps(entry)


def _setup_logging(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")

    logger = logging.getLogger("vault_tier_backup")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    txt_handler = RotatingFileHandler(
        os.path.join(log_dir, f"backup_log_{today_str}.log"), maxBytes=5 * 1024 * 1024, backupCount=5
    )
    txt_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(txt_handler)

    json_handler = logging.FileHandler(os.path.join(log_dir, f"backup_log_{today_str}.json"))
    json_handler.setFormatter(_JsonFormatter())
    logger.addHandler(json_handler)

    logger.addHandler(logging.StreamHandler())
    return logger


def should_upload_to_cloud(upload_to_cloud, day, monthly_zip_path_source):
    """Bug fix: was `upload_to_cloud & day == 1` (bitwise `&`, evaluated as
    `(upload_to_cloud & day) == 1`, true on every odd day rather than just the
    1st). Also requires the monthly zip path to actually exist, since it's
    only computed on day 1."""
    return bool(upload_to_cloud) and day == 1 and monthly_zip_path_source is not None


def _build_period_roots(backup_root):
    roots = {}
    for period in ("daily", "weekly", "monthly", "yearly"):
        path = os.path.join(backup_root, period)
        os.makedirs(path, exist_ok=True)
        roots[period] = path
    return roots


def run(config_path, dry_run_override=None):
    config = load_config(config_path)

    base_dir = os.path.dirname(os.path.abspath(config_path))
    control = config["control"]
    backup_cfg = config["backup"]
    paths_cfg = config["paths"]

    dry_run = control["dry_run"] if dry_run_override is None else dry_run_override

    backup_source = paths_cfg["backup_source"]
    backup_root_exe = os.path.join(base_dir, paths_cfg["backup_root_exe"])
    backup_root_source = os.path.join(backup_source, paths_cfg["backup_root_source"])
    os.makedirs(backup_root_exe, exist_ok=True)
    # Only create the second (source-drive) root when dual_backup actually uses
    # it — otherwise a single-destination setup leaves an empty folder in the
    # user's source directory.
    if backup_cfg["dual_backup"]:
        os.makedirs(backup_root_source, exist_ok=True)

    roots_exe = _build_period_roots(backup_root_exe)
    roots_source = _build_period_roots(backup_root_source)

    logger = _setup_logging(os.path.join(backup_root_exe, "logs"))

    extensions = tuple(backup_cfg["extensions"])
    skip_keywords = [k.lower() for k in backup_cfg.get("skip_keywords", [])]
    mirrors = config.get("mirrors", [])
    dual_backup = backup_cfg["dual_backup"]
    weekly_day = backup_cfg["weekly_day"]
    weekly_full_backup = backup_cfg["weekly_full_backup"]
    max_age_days = backup_cfg["max_age_days"]
    full_backup_mode = control.get("full_backup_mode", False)
    encrypt = control.get("encrypt", True)

    if not encrypt:
        logger.warning(
            "Encryption is OFF — backups are plain zip files. Anyone who can read "
            "the backup folder (or a mirror / cloud copy) can open your files. "
            "Turn it back on unless you specifically need unencrypted archives."
        )

    # Secrets are only required from the environment when the feature that
    # needs them is actually enabled and we're not in a dry run (dry runs never
    # touch the zip password, SMTP login, or OneDrive token). With encryption
    # off, no zip password is needed at all.
    zip_password = (
        get_required_env("BACKUP_ZIP_PASSWORD").encode() if (encrypt and not dry_run) else b""
    )

    email_password = None
    if control.get("email_enabled", False) and not dry_run:
        if config.get("email", {}).get("method", "smtp") == "smtp":
            email_password = get_required_env("BACKUP_EMAIL_PASSWORD")

    onedrive_secret = None
    if control.get("upload_to_cloud", False) and not dry_run:
        onedrive_secret = get_required_env("BACKUP_ONEDRIVE_CLIENT_SECRET")

    # Key-loss safeguard: verify the password matches the one that created any
    # existing backups here (or register it on first use) BEFORE writing a
    # single archive, so a changed/typo'd password aborts loudly instead of
    # silently producing unrecoverable backups. Dry runs never write, so skip.
    if not dry_run and encrypt:
        keyguard.ensure_token(backup_root_exe, zip_password)
        if dual_backup:
            keyguard.ensure_token(backup_root_source, zip_password)

    dest_roots = [backup_root_exe, backup_root_source] if dual_backup else [backup_root_exe]

    # 3-2-1 nudge: warn if nothing offsite protects against the source drive dying.
    mirror.warn_if_not_offsite(backup_source, dest_roots, mirrors)
    # Same-disk safety: warn if the primary backup shares the source's physical
    # disk — a single drive failure would take the originals and the backup.
    safety.warn_if_primary_on_source_disk(backup_source, dest_roots, has_mirror=bool(mirrors))

    today = datetime.now()

    # Bug fix: backup_type must be determined BEFORE days_limit is computed.
    # The original code checked backup_type=="weekly" while backup_type was
    # still hardcoded to "daily", so weekly_full_backup never actually applied.
    backup_type = state.determine_backup_type(today, weekly_day)
    days_limit = state.determine_days_limit(backup_type, weekly_full_backup, backup_root_exe, max_age_days)

    timestamp = today.strftime("%Y-%m-%d_%H-%M-%S")
    zip_name_exe = f"{timestamp}_{backup_type}.zip"
    zip_path_exe = os.path.join(backup_root_exe, zip_name_exe)
    zip_name_source = zip_name_exe
    zip_path_source = os.path.join(backup_root_source, zip_name_source)

    files = collector.get_files_to_backup(
        backup_source,
        extensions,
        backup_roots=[backup_root_exe, backup_root_source],
        skip_keywords=skip_keywords,
        days_limit=days_limit,
        include_subfolders=backup_cfg["include_subfolders_daily"],
        full_backup_mode=full_backup_mode,
    )
    if not files:
        # An empty set is normal on a quiet day (nothing changed within the mtime
        # window) — but alarming if the source has NO matching files at all, which
        # means a wrong path or wrong extensions. Distinguish the two.
        total_matching = collector.get_files_to_backup(
            backup_source, extensions, backup_roots=dest_roots,
            skip_keywords=skip_keywords, days_limit=None,
            include_subfolders=backup_cfg["include_subfolders_daily"],
            full_backup_mode=full_backup_mode,
        )
        if safety.looks_like_misconfiguration(len(files), len(total_matching)):
            logger.warning(
                "No files match extensions %s under '%s'. Nothing is being backed "
                "up — check the source folder and file types in your config.",
                list(extensions), backup_source,
            )
        else:
            logger.info("No files changed within the backup window — nothing to do today (normal).")

    # Disk-space pre-flight: warn before writing so a filling drive is visible
    # early instead of surfacing as a mid-write failure. dual_backup writes twice.
    if files and not dry_run:
        needed = sum(size for _, _, size, _ in files) * (2 if dual_backup else 1)
        safety.warn_low_disk_space(dest_roots, needed)

    total_size = 0
    skipped = []  # (rel_path, reason) for files locked/unreadable at backup time
    created = []  # (path, expected_member_count | None) to verify after writing
    if dual_backup:
        total_size += archive.create_encrypted_zip(files, zip_path_exe, zip_password, dry_run, skipped=skipped, encrypt=encrypt)
        total_size += archive.create_encrypted_zip(files, zip_path_source, zip_password, dry_run, encrypt=encrypt)
        created = [(zip_path_exe, len(files) - len(skipped)), (zip_path_source, None)]
        zip_names = f"{zip_name_exe} & {zip_name_source}"
    else:
        total_size = archive.create_encrypted_zip(files, zip_path_exe, zip_password, dry_run, skipped=skipped, encrypt=encrypt)
        created = [(zip_path_exe, len(files) - len(skipped))]
        zip_names = zip_name_exe

    if skipped:
        logger.warning(
            "%d file(s) were locked/unreadable and left OUT of this backup: %s",
            len(skipped),
            ", ".join(rel for rel, _ in skipped),
        )

    # Integrity check: re-open each freshly written archive and CRC-check every
    # member BEFORE anything downstream (move/prune/mirror) trusts it. A corrupt
    # backup is a hard failure — raise so monitoring alerts and success is never
    # recorded. Runs before retention so a bad backup can't trigger pruning.
    if control.get("verify_backups", True) and not dry_run:
        for path, expected in created:
            ok, detail = archive.verify_zip(path, zip_password, expected, encrypted=encrypt)
            if ok:
                logger.info(f"Verified integrity: {os.path.basename(path)} ({detail})")
            else:
                logger.error(f"INTEGRITY CHECK FAILED for {os.path.basename(path)}: {detail}")
                raise archive.BackupVerificationError(f"{os.path.basename(path)}: {detail}")

    if backup_type in ("daily", "weekly"):
        daily_exe_path = os.path.join(roots_exe["daily"], zip_name_exe)
        if not dry_run:
            os.rename(zip_path_exe, daily_exe_path)
            if dual_backup:
                os.rename(zip_path_source, os.path.join(roots_source["daily"], zip_name_source))
        else:
            logger.info(f"[DRY RUN] Would move {backup_type} ZIP to {roots_exe['daily']} & {roots_source['daily']}")

    if backup_type == "weekly":
        week_number = today.isocalendar().week
        weekly_zip_name = f"{today.year}-W{week_number:02d}_weekly.zip"
        weekly_exe_path = os.path.join(roots_exe["weekly"], weekly_zip_name)
        weekly_source_path = os.path.join(roots_source["weekly"], weekly_zip_name)

        if os.path.exists(weekly_exe_path):
            logger.info(f"Weekly backup already exists: {weekly_zip_name}")
        else:
            daily_zips_exe = archive.get_zips_for_hierarchy(roots_exe["daily"], "_daily.zip")
            if daily_zips_exe:
                logger.info(f"Packing {len(daily_zips_exe)} daily backups into weekly ZIP")
                archive.create_encrypted_zip(daily_zips_exe, weekly_exe_path, zip_password, dry_run)

            if dual_backup:
                daily_zips_source = archive.get_zips_for_hierarchy(roots_source["daily"], "_daily.zip")
                if daily_zips_source:
                    logger.info(f"Packing {len(daily_zips_source)} daily backups into weekly ZIP")
                    archive.create_encrypted_zip(daily_zips_source, weekly_source_path, zip_password, dry_run)

            if dry_run:
                logger.info("[DRY RUN] Would create weekly ZIP from daily backups")

    monthly_zip_path_source = None
    monthly_zip_name_source = None
    if today.day == 1:
        last_month = today.replace(day=1) - timedelta(days=1)
        month, year = last_month.month, last_month.year
        monthly_zip_name = f"{year}-{month:02d}_monthly.zip"
        monthly_zip_path_exe = os.path.join(roots_exe["monthly"], monthly_zip_name)
        monthly_zip_path_source = os.path.join(roots_source["monthly"], monthly_zip_name)
        monthly_zip_name_source = monthly_zip_name

        weekly_zips_exe = archive.get_zips_for_hierarchy(roots_exe["weekly"], "_weekly.zip", month, year)
        if weekly_zips_exe:
            logger.info(f"Packing {len(weekly_zips_exe)} weekly backups into monthly ZIP")
            archive.create_encrypted_zip(weekly_zips_exe, monthly_zip_path_exe, zip_password, dry_run)

        if dual_backup:
            weekly_zips_source = archive.get_zips_for_hierarchy(roots_source["weekly"], "_weekly.zip", month, year)
            if weekly_zips_source:
                logger.info(f"Packing {len(weekly_zips_source)} weekly backups into monthly ZIP")
                archive.create_encrypted_zip(weekly_zips_source, monthly_zip_path_source, zip_password, dry_run)

    if today.month == 1 and today.day == 1:
        last_year = today.year - 1
        yearly_zip_name = f"{last_year}_yearly.zip"
        yearly_zip_path_exe = os.path.join(roots_exe["yearly"], yearly_zip_name)
        yearly_zip_path_source = os.path.join(roots_source["yearly"], yearly_zip_name)

        monthly_zips_exe = archive.get_zips_for_hierarchy(roots_exe["monthly"], "_monthly.zip", year=last_year)
        if monthly_zips_exe:
            logger.info(f"Packing {len(monthly_zips_exe)} monthly backups into yearly ZIP")
            archive.create_encrypted_zip(monthly_zips_exe, yearly_zip_path_exe, zip_password, dry_run)

        if dual_backup:
            monthly_zips_source = archive.get_zips_for_hierarchy(
                roots_source["monthly"], "_monthly.zip", year=last_year
            )
            if monthly_zips_source:
                logger.info(f"Packing {len(monthly_zips_source)} monthly backups into yearly ZIP")
                archive.create_encrypted_zip(monthly_zips_source, yearly_zip_path_source, zip_password, dry_run)

    archive.delete_old_backups_by_config(
        config,
        {
            "daily_exe": roots_exe["daily"],
            "daily_source": roots_source["daily"],
            "weekly_exe": roots_exe["weekly"],
            "weekly_source": roots_source["weekly"],
            "monthly_exe": roots_exe["monthly"],
            "monthly_source": roots_source["monthly"],
            "yearly_exe": roots_exe["yearly"],
            "yearly_source": roots_source["yearly"],
        },
        dry_run,
    )

    # Offsite replica: copy the finalized tier tree (and key token) to each
    # configured mirror. Runs after retention so mirrors match the pruned set.
    copied = mirror.sync_mirrors(backup_root_exe, mirrors, dry_run)
    if mirrors:
        logger.info(f"Mirror sync: {copied} file(s) {'would be ' if dry_run else ''}copied to {len(mirrors)} mirror(s).")

    if should_upload_to_cloud(control.get("upload_to_cloud", False), today.day, monthly_zip_path_source):
        onedrive_cfg = config["cloud"]["onedrive"]
        cloud.upload_to_cloud(
            monthly_zip_path_source,
            monthly_zip_name_source,
            control["cloud_platform"],
            onedrive_cfg["client_id"],
            onedrive_secret,
            onedrive_cfg["tenant_id"],
            onedrive_cfg["upload_path"],
            dry_run=dry_run,
            upload_enabled=control["upload_to_cloud"],
        )

    notify.notify(
        config, email_password, zip_names, backup_type,
        num_files=len(files), total_size=total_size, dry_run=dry_run,
        skipped_count=len(skipped),
    )

    if skipped:
        logger.info(
            f"{backup_type.upper()} backup completed with {len(skipped)} file(s) skipped (locked)."
        )
    else:
        logger.info(f"{backup_type.upper()} backup completed successfully.")
    state.save_last_run_time(backup_root_exe, today)


def _resolve_roots(config_path):
    """Return (backup_root_exe, backup_root_source) from a config file, matching
    how run() computes them."""
    config = load_config(config_path)
    base_dir = os.path.dirname(os.path.abspath(config_path))
    paths_cfg = config["paths"]
    backup_root_exe = os.path.join(base_dir, paths_cfg["backup_root_exe"])
    backup_root_source = os.path.join(paths_cfg["backup_source"], paths_cfg["backup_root_source"])
    return backup_root_exe, backup_root_source


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


def run_monitored(config_path, dry_run_override=None):
    """Wrap a backup run with silent-failure monitoring: a start-of-run
    staleness check, a heartbeat ping on success, and a /fail ping plus failure
    alert on any exception (then re-raise)."""
    config = load_config(config_path)
    monitoring = config.get("monitoring", {})
    heartbeat_url = monitoring.get("heartbeat_url", "")
    max_quiet_hours = monitoring.get("max_quiet_hours")
    alert_on_failure = monitoring.get("alert_on_failure", True)
    dry_run = config["control"]["dry_run"] if dry_run_override is None else dry_run_override

    backup_root_exe, _ = _resolve_roots(config_path)
    monitor.check_staleness(backup_root_exe, max_quiet_hours)

    try:
        run(config_path, dry_run_override=dry_run_override)
    except Exception as exc:
        monitor.ping_heartbeat(heartbeat_url, "/fail", dry_run)
        if alert_on_failure:
            notify.notify_failure(config, str(exc), dry_run)
        raise
    monitor.ping_heartbeat(heartbeat_url, "", dry_run)


def cmd_backup(args):
    run_monitored(args.config, dry_run_override=args.dry_run)


def cmd_list(args):
    backup_root_exe, _ = _resolve_roots(args.config)
    entries = restore.list_backups(backup_root_exe)
    if not entries:
        print(f"No backups found under {backup_root_exe}")
        return
    print(f"{'TIER':<8} {'SIZE':>10}  {'MODIFIED':<19}  NAME")
    for e in entries:
        if args.tier and e["tier"] != args.tier:
            continue
        mtime = datetime.fromtimestamp(e["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{e['tier']:<8} {_human_size(e['size']):>10}  {mtime:<19}  {e['name']}")
        if args.contents:
            for member in restore.list_contents(e["path"]):
                print(f"           - {member}")


def cmd_restore(args):
    backup_root_exe, _ = _resolve_roots(args.config)
    password = get_required_env("BACKUP_ZIP_PASSWORD")
    written = restore.restore_archive(
        backup_root_exe, args.archive, args.to, password, member=args.member, deep=args.deep
    )
    print(f"Restored {len(written)} item(s) to {args.to}")


def cmd_init(args):
    return wizard.run_wizard(args.config)


def cmd_gui(args):
    from . import gui  # imported lazily so headless installs don't need tkinter
    return gui.launch(args.config)


def cmd_install_schedule(args):
    print(schedule.install_schedule(args.config, time_str=args.time, task_name=args.name))


def cmd_uninstall_schedule(args):
    print(schedule.uninstall_schedule(task_name=args.name))


def cmd_check_key(args):
    backup_root_exe, backup_root_source = _resolve_roots(args.config)
    password = get_required_env("BACKUP_ZIP_PASSWORD")
    checked = 0
    for root in (backup_root_exe, backup_root_source):
        if os.path.exists(keyguard.token_path(root)):
            keyguard.verify_password(root, password)  # raises on mismatch
            print(f"OK: password matches backups in {root}")
            checked += 1
    if checked == 0:
        print("No key token found yet — the first real backup will register this password.")


def cmd_test_restore(args):
    """Fire-drill: actually restore the newest backup to a temp folder and
    confirm it comes out. A backup you've never restored from is a guess."""
    backup_root_exe, backup_root_source = _resolve_roots(args.config)
    password = get_required_env("BACKUP_ZIP_PASSWORD")
    ok_any = False
    for root in (backup_root_exe, backup_root_source):
        if not restore.list_backups(root):
            continue
        ok, detail = safety.test_restore(root, password, archive_name=args.archive)
        marker = "OK" if ok else "FAILED"
        print(f"[{marker}] {root}: {detail}")
        ok_any = ok_any or ok
        if not ok:
            return 1
    if not ok_any:
        print("No backups found yet to test — run a backup first.")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="vault-tier-backup", description=__doc__)
    parser.add_argument("-c", "--config", default="config.json", help="Path to config.json (default: ./config.json)")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Interactive setup — create config.json and set the password")
    p_init.set_defaults(func=cmd_init)

    p_gui = sub.add_parser("gui", help="Open the desktop app (no JSON, no command line)")
    p_gui.set_defaults(func=cmd_gui)

    p_backup = sub.add_parser("backup", help="Run a backup (default action)")
    p_backup.add_argument("--dry-run", action="store_true", default=None, help="Force dry-run regardless of config")
    p_backup.set_defaults(func=cmd_backup)

    p_list = sub.add_parser("list", help="List existing backups")
    p_list.add_argument("--tier", choices=restore.TIERS, help="Only show one tier")
    p_list.add_argument("--contents", action="store_true", help="Also list files inside each archive")
    p_list.set_defaults(func=cmd_list)

    p_restore = sub.add_parser("restore", help="Restore an archive")
    p_restore.add_argument("archive", help="Archive filename (e.g. 2026-07-10_..._daily.zip) or full path")
    p_restore.add_argument("--to", default="restored", help="Destination directory (default: ./restored)")
    p_restore.add_argument("--member", help="Restore only this file from inside the archive")
    p_restore.add_argument("--deep", action="store_true", help="Recursively unpack nested rollup archives")
    p_restore.set_defaults(func=cmd_restore)

    p_check = sub.add_parser("check-key", help="Verify BACKUP_ZIP_PASSWORD matches existing backups")
    p_check.set_defaults(func=cmd_check_key)

    p_testr = sub.add_parser("test-restore", help="Fire-drill: restore the newest backup to a temp folder to prove it works")
    p_testr.add_argument("--archive", help="Test a specific archive by name instead of the newest")
    p_testr.set_defaults(func=cmd_test_restore)

    p_sched = sub.add_parser("install-schedule", help="Register a daily backup (Windows Task Scheduler / cron)")
    p_sched.add_argument("--time", default=schedule.DEFAULT_TIME, help="Daily run time HH:MM (default 20:00)")
    p_sched.add_argument("--name", default=schedule.DEFAULT_TASK_NAME, help="Scheduled task name")
    p_sched.set_defaults(func=cmd_install_schedule)

    p_unsched = sub.add_parser("uninstall-schedule", help="Remove the scheduled daily backup")
    p_unsched.add_argument("--name", default=schedule.DEFAULT_TASK_NAME, help="Scheduled task name")
    p_unsched.set_defaults(func=cmd_uninstall_schedule)

    args = parser.parse_args()

    # No subcommand -> default to backup, preserving prior behavior.
    if not getattr(args, "command", None):
        args.func = cmd_backup
        args.dry_run = None

    try:
        rc = args.func(args)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    if rc:
        sys.exit(rc)


if __name__ == "__main__":
    main()
