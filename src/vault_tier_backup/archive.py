import logging
import os
from datetime import datetime, timedelta

import pyzipper

logger = logging.getLogger(__name__)


def create_encrypted_zip(files_list, zip_path, password, dry_run=False):
    total_size = 0

    if os.path.exists(zip_path):
        logger.info(f"Backup already exists. Skipping creation: {zip_path}")
        return 0

    if dry_run:
        logger.info(f"[DRY RUN] Would create ZIP: {zip_path}")
        for _, rel_path, size_bytes, depth in files_list:
            logger.info(f"[DRY RUN] Include {rel_path} size={size_bytes} depth={depth}")
            total_size += size_bytes
        return total_size

    try:
        with pyzipper.AESZipFile(
            zip_path, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
        ) as zipf:
            zipf.setpassword(password)
            for full_path, rel_path, size_bytes, depth in files_list:
                zipf.write(full_path, arcname=rel_path)
                logger.info(f"Added {rel_path} size={size_bytes} depth={depth}")
                total_size += size_bytes
    except Exception as e:
        logger.error(f"ZIP creation failed: {e}")
    return total_size


def delete_old_backups(root_folder, suffix, cutoff, dry_run=False):
    for f in os.listdir(root_folder):
        if not f.endswith(suffix):
            continue
        file_path = os.path.join(root_folder, f)
        file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
        if file_mtime < cutoff:
            if dry_run:
                logger.info(f"[DRY RUN] Would delete: {f}")
            else:
                os.remove(file_path)
                logger.info(f"Deleted old backup: {f}")


def delete_old_backups_by_config(config, roots, dry_run=False):
    """roots keys: daily_exe, daily_source, weekly_exe, weekly_source,
    monthly_exe, monthly_source, yearly_exe, yearly_source."""
    today = datetime.now()
    retention = config["retention"]
    control = config["control"]
    dual_backup = config["backup"]["dual_backup"]

    if control.get("delete_old_daily", False):
        cutoff = today - timedelta(days=retention["daily_keep"])
        delete_old_backups(roots["daily_exe"], "_daily.zip", cutoff, dry_run)
        if dual_backup:
            delete_old_backups(roots["daily_source"], "_daily.zip", cutoff, dry_run)

    if control.get("delete_old_weekly", False):
        cutoff = today - timedelta(weeks=retention["weekly_keep"])
        delete_old_backups(roots["weekly_exe"], "_weekly.zip", cutoff, dry_run)
        if dual_backup:
            delete_old_backups(roots["weekly_source"], "_weekly.zip", cutoff, dry_run)

    # Bug fix: config key used to be misspelled "delete_old_montly" and never matched
    # this "delete_old_monthly" lookup, so monthly cleanup silently never ran.
    if control.get("delete_old_monthly", False):
        cutoff = today - timedelta(days=retention["monthly_keep"] * 30)
        delete_old_backups(roots["monthly_exe"], "_monthly.zip", cutoff, dry_run)
        if dual_backup:
            delete_old_backups(roots["monthly_source"], "_monthly.zip", cutoff, dry_run)

    if control.get("delete_old_yearly", False):
        cutoff = today - timedelta(days=retention["yearly_keep"] * 365)
        delete_old_backups(roots["yearly_exe"], "_yearly.zip", cutoff, dry_run)
        if dual_backup:
            delete_old_backups(roots["yearly_source"], "_yearly.zip", cutoff, dry_run)


def get_zips_for_hierarchy(root_folder, level_suffix, month=None, year=None):
    """Collect ZIP files for monthly/yearly backups, filtered by month/year."""
    zips = []
    try:
        files = os.listdir(root_folder)
    except OSError:
        return zips

    for f in files:
        if not f.endswith(level_suffix):
            continue
        file_path = os.path.join(root_folder, f)
        file_date_str = f.split("_")[0]

        file_date = None
        try:
            file_date = datetime.strptime(file_date_str, "%Y-%m-%d")
        except ValueError:
            try:
                file_date = datetime.strptime(file_date_str + "-1", "%Y-W%W-%w")
            except ValueError:
                try:
                    file_date = datetime.strptime(file_date_str + "-01", "%Y-%m-%d")
                except ValueError:
                    logger.debug(f"Skipping file {f}, cannot parse date")
                    continue

        if month and file_date.month != month:
            continue
        if year and file_date.year != year:
            continue

        try:
            size_bytes = os.path.getsize(file_path)
        except OSError:
            continue

        zips.append((file_path, f, size_bytes, 0))

    return zips
