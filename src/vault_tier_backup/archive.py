import logging
import os
import time
from datetime import datetime, timedelta

import pyzipper

logger = logging.getLogger(__name__)

# A file locked by Excel/Access is usually only busy for a few seconds (during a
# save). Retry briefly before giving up so transient locks don't cost a file.
DEFAULT_LOCK_RETRIES = 2
DEFAULT_LOCK_RETRY_DELAY = 3  # seconds


class BackupVerificationError(Exception):
    """Raised when a freshly written archive fails its integrity check."""


def verify_zip(zip_path, password, expected_count=None):
    """Re-open a freshly written archive and confirm it's readable and intact:
    decrypt and CRC-check every member (testzip), and optionally confirm the
    member count. Returns (ok: bool, detail: str). Never raises — turns any
    failure into ok=False so the caller decides how loud to be."""
    if isinstance(password, str):
        password = password.encode()
    try:
        with pyzipper.AESZipFile(zip_path) as zf:
            zf.setpassword(password)
            bad = zf.testzip()  # reads + decrypts + CRC-checks each member
            if bad is not None:
                return False, f"corrupt member: {bad}"
            count = len(zf.namelist())
    except Exception as e:
        return False, f"could not open/verify: {e}"

    if expected_count is not None and count != expected_count:
        return False, f"expected {expected_count} members, found {count}"
    return True, f"{count} members OK"


def _add_file_with_retry(zipf, full_path, rel_path, retries, retry_delay):
    """Write one file into the open zip, retrying on a lock (PermissionError /
    OSError, e.g. Windows "file in use"). Raises the last error if it never
    frees up."""
    attempt = 0
    while True:
        try:
            zipf.write(full_path, arcname=rel_path)
            return
        except (PermissionError, OSError) as e:
            if attempt >= retries:
                raise
            attempt += 1
            logger.warning(
                f"'{rel_path}' is locked ({e}); retry {attempt}/{retries} in {retry_delay}s"
            )
            time.sleep(retry_delay)


def create_encrypted_zip(
    files_list,
    zip_path,
    password,
    dry_run=False,
    skipped=None,
    retries=DEFAULT_LOCK_RETRIES,
    retry_delay=DEFAULT_LOCK_RETRY_DELAY,
):
    """Create one AES-encrypted zip from files_list.

    Each file is added independently: a file that stays locked (open in Excel/
    Access) is skipped with a warning and the rest of the backup still
    completes — one open file must never abandon the whole archive. If a
    ``skipped`` list is passed, (rel_path, reason) is appended for each casualty
    so the caller can report them. Returns the total size of files added.
    """
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
                try:
                    _add_file_with_retry(zipf, full_path, rel_path, retries, retry_delay)
                except (PermissionError, OSError) as e:
                    logger.error(f"Skipped '{rel_path}' — could not read (still locked?): {e}")
                    if skipped is not None:
                        skipped.append((rel_path, str(e)))
                    continue
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
