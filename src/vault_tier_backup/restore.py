"""List and restore from the encrypted backups.

A backup you can't restore from isn't a backup. These functions read the same
tiered folder layout the backup run produces (daily/weekly/monthly/yearly) and
extract archives, verifying the password up front so a wrong password fails
with a clear message instead of a cryptic zip error mid-extract.

Note on nesting: weekly archives contain the daily zips, monthly contain the
weekly zips, and yearly contain the monthly zips. Restoring a rollup therefore
yields the inner zips; pass deep=True to unpack them recursively (they share
the same password).
"""

import logging
import os

import pyzipper

from . import keyguard

logger = logging.getLogger(__name__)

TIERS = ("daily", "weekly", "monthly", "yearly")


def list_backups(backup_root):
    """Return a list of dicts describing every archive under a backup root,
    newest first: {tier, name, path, size, mtime}."""
    entries = []
    for tier in TIERS:
        tier_dir = os.path.join(backup_root, tier)
        if not os.path.isdir(tier_dir):
            continue
        for name in os.listdir(tier_dir):
            if not name.lower().endswith(".zip"):
                continue
            path = os.path.join(tier_dir, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            entries.append(
                {
                    "tier": tier,
                    "name": name,
                    "path": path,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries


def list_contents(archive_path):
    """Return the member names inside an archive (no password needed for the
    listing itself)."""
    with pyzipper.AESZipFile(archive_path) as zf:
        return zf.namelist()


def find_archive(backup_root, archive_name):
    """Locate an archive by exact filename across the tier folders. Returns the
    full path, or None if not found."""
    for tier in TIERS:
        candidate = os.path.join(backup_root, tier, archive_name)
        if os.path.isfile(candidate):
            return candidate
    return None


def restore_archive(backup_root, archive, dest_dir, password, member=None, deep=False):
    """Extract an archive (by name or full path) into dest_dir.

    Verifies the password against the backup root's key token first, so a wrong
    password aborts clearly before any extraction. Returns the list of paths
    written.
    """
    keyguard.verify_password(backup_root, password)  # raises PasswordMismatchError on mismatch

    archive_path = archive if os.path.isfile(archive) else find_archive(backup_root, archive)
    if not archive_path:
        raise FileNotFoundError(f"Archive not found in {backup_root}: {archive}")

    os.makedirs(dest_dir, exist_ok=True)
    if isinstance(password, str):
        password = password.encode()

    written = []
    with pyzipper.AESZipFile(archive_path) as zf:
        zf.setpassword(password)
        members = [member] if member else zf.namelist()
        for name in members:
            zf.extract(name, dest_dir)
            written.append(os.path.join(dest_dir, name))
            logger.info(f"Restored {name} -> {dest_dir}")

    if deep:
        for path in list(written):
            if path.lower().endswith(".zip") and os.path.isfile(path):
                inner_dest = os.path.join(dest_dir, os.path.basename(path) + "_unpacked")
                logger.info(f"Deep-unpacking nested archive {os.path.basename(path)}")
                written.extend(
                    restore_archive(backup_root, path, inner_dest, password, deep=True)
                )

    return written
