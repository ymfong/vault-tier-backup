"""Offsite / 3-2-1 replica sync.

The backup is only real if a copy survives the source dying. By default this
tool writes archives next to the source (and optionally a second copy under the
source drive) — but if both live on the same physical volume, one disk failure,
ransomware hit, or corruption takes the source AND every backup with it.

A *mirror* is an extra destination — another drive, an external disk, a network
share — that the full tier tree is replicated to after each run. Configure at
least one on a different physical device and you have a genuine offsite copy.
`warn_if_not_offsite` nags loudly when no mirror is set and the backups share a
volume with the source, so the gap is visible instead of silent.
"""

import logging
import os
import shutil

from .keyguard import TOKEN_FILENAME
from .restore import TIERS

logger = logging.getLogger(__name__)


def volume_of(path):
    """Return a comparable volume identifier for a path (drive letter or UNC
    share), case-folded. Works on paths that don't exist yet."""
    drive, _ = os.path.splitdrive(os.path.abspath(path))
    return drive.casefold()


def same_volume(path_a, path_b):
    return volume_of(path_a) == volume_of(path_b)


def warn_if_not_offsite(backup_source, backup_roots, mirrors):
    """Log a warning if there's no offsite protection: no mirrors configured and
    at least one backup root sharing a volume with the source."""
    if mirrors:
        return
    on_source_volume = [r for r in backup_roots if same_volume(r, backup_source)]
    if on_source_volume:
        logger.warning(
            "No offsite mirror configured and backups live on the same volume "
            "as the source (%s). If that drive fails or is hit by ransomware, "
            "the source and every backup are lost together. Set 'mirrors' in "
            "your config to a location on a different physical device.",
            volume_of(backup_source) or backup_source,
        )


def _needs_copy(src, dst):
    if not os.path.exists(dst):
        return True
    src_stat, dst_stat = os.stat(src), os.stat(dst)
    return src_stat.st_size != dst_stat.st_size or src_stat.st_mtime > dst_stat.st_mtime


def sync_mirrors(backup_root, mirrors, dry_run=False):
    """Replicate the tier archives (and the key-verification token) from
    backup_root into each mirror destination. Idempotent — only missing or
    changed files are copied. A mirror that's unreachable logs a warning and is
    skipped rather than failing the whole run.

    Returns the number of files copied across all mirrors.
    """
    if not mirrors:
        return 0

    copied = 0
    for mirror in mirrors:
        try:
            copied += _sync_one_mirror(backup_root, mirror, dry_run)
        except OSError as e:
            logger.warning(f"Mirror '{mirror}' is unreachable, skipping this run: {e}")
            continue
    return copied


def _iter_source_files(backup_root):
    """Yield (relative_path, absolute_path) for every file that should be
    mirrored: the tier zips plus the key token."""
    for tier in TIERS:
        tier_dir = os.path.join(backup_root, tier)
        if not os.path.isdir(tier_dir):
            continue
        for name in os.listdir(tier_dir):
            if name.lower().endswith(".zip"):
                yield os.path.join(tier, name), os.path.join(tier_dir, name)

    token = os.path.join(backup_root, TOKEN_FILENAME)
    if os.path.isfile(token):
        yield TOKEN_FILENAME, token


def _sync_one_mirror(backup_root, mirror, dry_run):
    """Copy missing/changed files into one mirror. Returns the count copied (or,
    in dry-run, the count that would be copied)."""
    count = 0
    for rel_path, src in _iter_source_files(backup_root):
        dst = os.path.join(mirror, rel_path)
        if not _needs_copy(src, dst):
            continue
        count += 1
        if dry_run:
            logger.info(f"[DRY RUN] Would mirror {rel_path} -> {mirror}")
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        logger.info(f"Mirrored {rel_path} -> {mirror}")
    return count
