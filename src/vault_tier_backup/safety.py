"""Pre-flight safety checks that turn silent failures into visible warnings.

These guard the failure modes a non-technical user never sees coming:
- the "backup" sitting on the same physical disk as the source (one failure
  loses both),
- a mistyped folder or wrong file types producing a cheerful empty backup,
- the destination drive quietly filling up,
- and backups nobody has ever actually restored from.

The decision logic here is kept as pure functions so it can be tested without a
real disk; `run.py` calls the `warn_*` wrappers, which log and return the
problems they found so a caller (or the future GUI) can surface them.
"""

import logging
import os
import shutil
import tempfile

from . import mirror, restore

logger = logging.getLogger(__name__)

# Comfort floor: warn once free space dips below this even if this run fits.
DEFAULT_MIN_FREE_BYTES = 500 * 1024 * 1024  # 500 MB


def human_size(num_bytes):
    if num_bytes is None:
        return "unknown"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024


# --- 1. Same-disk destination -------------------------------------------------

def destinations_on_source_disk(backup_source, dest_roots):
    """Which of dest_roots live on the same physical volume as the source."""
    return [r for r in dest_roots if mirror.same_volume(r, backup_source)]


def warn_if_primary_on_source_disk(backup_source, dest_roots, has_mirror):
    """Warn when a primary backup destination shares the source's disk. A single
    disk failure (or ransomware) then takes the originals AND the backup. Returns
    the offending roots so callers can surface the same fact."""
    offenders = destinations_on_source_disk(backup_source, dest_roots)
    if offenders:
        tail = (
            "Your offsite mirror still protects you, but the local copy is not a "
            "safety net against that drive failing."
            if has_mirror
            else "Add an offsite 'mirror' on a different physical device."
        )
        logger.warning(
            "Backup destination is on the SAME disk as the source (%s). If that "
            "drive fails, the source and this backup are lost together. %s",
            mirror.volume_of(backup_source) or backup_source,
            tail,
        )
    return offenders


# --- 2. Empty / misconfigured backup -----------------------------------------

def looks_like_misconfiguration(recent_count, total_matching_count):
    """No files to back up is only alarming if the source contains *no* matching
    files at all — that's a wrong path or wrong extensions. If matching files
    exist but none changed recently, an empty daily run is perfectly normal."""
    return recent_count == 0 and total_matching_count == 0


# --- 3. Free space ------------------------------------------------------------

def _free_bytes(path):
    """Free bytes on the volume holding path, walking up to the nearest existing
    ancestor (the destination folder may not exist yet). None if undeterminable."""
    p = os.path.abspath(path)
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def free_space_status(dest, needed_bytes, min_free_bytes=DEFAULT_MIN_FREE_BYTES):
    """Return (ok, free_bytes, reason). ok is False when free space is below the
    estimated need or the comfort floor. Undeterminable free space never blocks."""
    free = _free_bytes(dest)
    if free is None:
        return True, None, ""
    if free < needed_bytes:
        return False, free, (
            f"only {human_size(free)} free but this backup needs about "
            f"{human_size(needed_bytes)}"
        )
    if free < min_free_bytes:
        return False, free, (
            f"only {human_size(free)} free (below the {human_size(min_free_bytes)} "
            f"safety floor)"
        )
    return True, free, ""


def warn_low_disk_space(dest_roots, needed_bytes, min_free_bytes=DEFAULT_MIN_FREE_BYTES):
    """Warn for any destination low on space. Returns list of (root, reason)."""
    problems = []
    for root in dest_roots:
        ok, _free, reason = free_space_status(root, needed_bytes, min_free_bytes)
        if not ok:
            logger.warning("Low disk space at '%s': %s.", root, reason)
            problems.append((root, reason))
    return problems


# --- 4. Restore fire-drill ----------------------------------------------------

def test_restore(backup_root, password, archive_name=None):
    """Prove the newest (or named) backup can actually be restored: extract it to
    a throwaway temp folder, confirm files come out, then clean up. Returns
    (ok, detail). This is the drill that turns 'I have backups' into 'I have
    backups I've restored from'."""
    entries = restore.list_backups(backup_root)
    if not entries:
        return False, f"no backups found under {backup_root}"

    if archive_name:
        target = next((e for e in entries if e["name"] == archive_name), None)
        if target is None:
            return False, f"archive '{archive_name}' not found under {backup_root}"
    else:
        target = entries[0]  # list_backups is newest-first

    dest = tempfile.mkdtemp(prefix="vtb-restore-test-")
    try:
        written = restore.restore_archive(backup_root, target["path"], dest, password)
        if not written:
            return False, f"'{target['name']}' restored but produced no files"
        return True, f"restored '{target['name']}' -> {len(written)} item(s) OK"
    except Exception as e:  # password mismatch, corruption, bad zip — all are failures
        return False, f"restore of '{target['name']}' FAILED: {e}"
    finally:
        shutil.rmtree(dest, ignore_errors=True)
