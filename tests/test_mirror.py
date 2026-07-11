import os

from vault_tier_backup import mirror
from vault_tier_backup.keyguard import TOKEN_FILENAME


def _make_backup_root(tmp_path):
    root = tmp_path / "out"
    (root / "daily").mkdir(parents=True)
    (root / "weekly").mkdir()
    (root / "daily" / "2026-07-10_daily.zip").write_bytes(b"daily-archive")
    (root / "weekly" / "2026-W28_weekly.zip").write_bytes(b"weekly-archive")
    (root / TOKEN_FILENAME).write_text("{}")
    return root


def test_same_volume_detection():
    assert mirror.same_volume("C:\\a\\b", "C:\\c\\d") is True
    assert mirror.same_volume("C:\\a", "D:\\a") is False


def test_sync_copies_tier_tree_and_token(tmp_path):
    root = _make_backup_root(tmp_path)
    dest = tmp_path / "mirror"

    copied = mirror.sync_mirrors(str(root), [str(dest)], dry_run=False)

    assert copied == 3  # 2 zips + token
    assert (dest / "daily" / "2026-07-10_daily.zip").read_bytes() == b"daily-archive"
    assert (dest / "weekly" / "2026-W28_weekly.zip").read_bytes() == b"weekly-archive"
    assert (dest / TOKEN_FILENAME).exists()


def test_sync_is_incremental(tmp_path):
    root = _make_backup_root(tmp_path)
    dest = tmp_path / "mirror"

    first = mirror.sync_mirrors(str(root), [str(dest)], dry_run=False)
    second = mirror.sync_mirrors(str(root), [str(dest)], dry_run=False)

    assert first == 3
    assert second == 0  # nothing changed -> nothing recopied


def test_sync_picks_up_new_archive(tmp_path):
    root = _make_backup_root(tmp_path)
    dest = tmp_path / "mirror"
    mirror.sync_mirrors(str(root), [str(dest)], dry_run=False)

    (root / "daily" / "2026-07-11_daily.zip").write_bytes(b"new-daily")
    copied = mirror.sync_mirrors(str(root), [str(dest)], dry_run=False)

    assert copied == 1
    assert (dest / "daily" / "2026-07-11_daily.zip").exists()


def test_dry_run_copies_nothing(tmp_path):
    root = _make_backup_root(tmp_path)
    dest = tmp_path / "mirror"

    copied = mirror.sync_mirrors(str(root), [str(dest)], dry_run=True)

    assert copied == 3  # reports what it *would* copy
    assert not dest.exists()  # but writes nothing


def test_no_mirrors_is_noop(tmp_path):
    root = _make_backup_root(tmp_path)
    assert mirror.sync_mirrors(str(root), [], dry_run=False) == 0
