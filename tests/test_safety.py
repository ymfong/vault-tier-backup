"""Pre-flight safety checks — same-disk, empty/misconfig, free space, fire-drill."""

import os

import pytest

from vault_tier_backup import archive, safety


# --- same-disk ----------------------------------------------------------------

def test_same_disk_detection_flags_shared_volume(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "backups"       # same tmp volume as source
    source.mkdir()
    dest.mkdir()
    offenders = safety.destinations_on_source_disk(str(source), [str(dest)])
    assert str(dest) in offenders


def test_same_disk_ignores_different_windows_volume():
    if os.name != "nt":
        pytest.skip("drive-letter semantics are Windows-only")
    offenders = safety.destinations_on_source_disk("C:\\data", ["D:\\backups"])
    assert offenders == []


def test_warn_primary_on_source_disk_returns_offenders(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    offenders = safety.warn_if_primary_on_source_disk(
        str(source), [str(tmp_path / "bak")], has_mirror=False
    )
    assert offenders  # same tmp volume


# --- empty / misconfiguration -------------------------------------------------

def test_misconfiguration_only_when_nothing_matches_at_all():
    # No recent files AND no matching files anywhere -> wrong path/extensions.
    assert safety.looks_like_misconfiguration(recent_count=0, total_matching_count=0) is True
    # No recent files but matches exist -> normal quiet day, not a problem.
    assert safety.looks_like_misconfiguration(recent_count=0, total_matching_count=12) is False
    # Files to back up -> obviously fine.
    assert safety.looks_like_misconfiguration(recent_count=3, total_matching_count=12) is False


# --- free space ---------------------------------------------------------------

def test_free_space_ok_when_plenty(tmp_path):
    ok, free, reason = safety.free_space_status(str(tmp_path), needed_bytes=1, min_free_bytes=1)
    assert ok and reason == "" and free > 0


def test_free_space_flags_insufficient(tmp_path):
    huge = 10 ** 18  # ~1 EB, larger than any real disk
    ok, _free, reason = safety.free_space_status(str(tmp_path), needed_bytes=huge, min_free_bytes=1)
    assert not ok
    assert "needs about" in reason


def test_free_space_flags_below_comfort_floor(tmp_path):
    # Need is tiny but the comfort floor is astronomically high -> warn.
    ok, _free, reason = safety.free_space_status(str(tmp_path), needed_bytes=1, min_free_bytes=10 ** 18)
    assert not ok
    assert "safety floor" in reason


def test_free_space_undeterminable_never_blocks():
    ok, free, reason = safety.free_space_status("Z:\\nonexistent\\path\\xyz", needed_bytes=10 ** 18)
    # If the volume can't be resolved at all, we must not block the backup.
    if free is None:
        assert ok is True and reason == ""


def test_human_size_rounds():
    assert safety.human_size(0) == "0 B"
    assert safety.human_size(1536).endswith("KB")
    assert safety.human_size(None) == "unknown"


# --- fire-drill restore -------------------------------------------------------

def _make_backup(tmp_path, password):
    """Create a real daily archive under a backup root, with a key token."""
    from vault_tier_backup import keyguard
    root = tmp_path / "bak"
    daily = root / "daily"
    daily.mkdir(parents=True)
    keyguard.ensure_token(str(root), password)

    src = tmp_path / "book.xlsx"
    src.write_bytes(b"payload-1234")
    files = [(str(src), "book.xlsx", src.stat().st_size, 0)]
    archive.create_encrypted_zip(files, str(daily / "2026-07-10_daily.zip"), password)
    return str(root)


def test_test_restore_succeeds_on_good_backup(tmp_path):
    pw = b"drill-pw"
    root = _make_backup(tmp_path, pw)
    ok, detail = safety.test_restore(root, pw)
    assert ok, detail
    assert "OK" in detail


def test_test_restore_fails_on_wrong_password(tmp_path):
    root = _make_backup(tmp_path, b"right-pw")
    ok, detail = safety.test_restore(root, b"wrong-pw")
    assert not ok
    assert "FAILED" in detail


def test_test_restore_reports_when_no_backups(tmp_path):
    ok, detail = safety.test_restore(str(tmp_path / "empty"), b"pw")
    assert not ok
    assert "no backups" in detail
