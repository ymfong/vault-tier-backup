"""Real (non-dry-run) backup + restore round trip.

This is the "prove it" test: it creates a real AES-encrypted archive, confirms
the encryption is real (wrong password fails), restores with the right
password, and asserts the restored bytes match the source exactly. It also
exercises the key-loss safeguard (a changed password must abort).
"""

import json
from datetime import datetime

import pyzipper
import pytest

from vault_tier_backup import archive, keyguard, restore
from vault_tier_backup.run import run

PASSWORD = "correct horse battery staple"


def _write_config(tmp_path, source_dir):
    # Pick a weekly_day that is NOT today so the run stays on the deterministic
    # daily path (no weekly rollup packing to reason about).
    non_today = (datetime.now().weekday() + 1) % 7
    config = {
        "paths": {
            "backup_source": str(source_dir),
            "backup_root_exe": "out",
            "backup_root_source": "bak",
        },
        "backup": {
            "extensions": [".xlsx", ".accdb"],
            "include_subfolders_daily": True,
            "weekly_day": non_today,
            "weekly_full_backup": True,
            "dual_backup": False,
            "max_age_days": 1,
            "skip_keywords": ["~$"],
        },
        "control": {
            "dry_run": True,
            "email_enabled": False,
            "upload_to_cloud": False,
            "cloud_platform": "onedrive",
            "delete_old_daily": False,
            "delete_old_weekly": False,
            "delete_old_monthly": False,
            "delete_old_yearly": False,
            "full_backup_mode": False,
        },
        "retention": {"daily_keep": 7, "weekly_keep": 5, "monthly_keep": 12, "yearly_keep": 2},
        "email": {"method": "smtp", "smtp_server": "x", "smtp_port": 587, "from": "a@b.c", "to": "a@b.c"},
        "cloud": {"onedrive": {"client_id": "x", "tenant_id": "y", "upload_path": "z"}},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def _find_daily_zip(tmp_path):
    daily_dir = tmp_path / "out" / "daily"
    zips = list(daily_dir.glob("*_daily.zip"))
    assert zips, f"no daily zip produced in {daily_dir}"
    return zips[0]


def test_run_aborts_when_integrity_check_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_ZIP_PASSWORD", PASSWORD)
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.xlsx").write_bytes(b"data")
    config_path = _write_config(tmp_path, source)

    # Simulate a corrupt freshly-written archive: verification reports failure.
    monkeypatch.setattr(archive, "verify_zip", lambda *a, **k: (False, "corrupt member: book.xlsx"))

    with pytest.raises(archive.BackupVerificationError):
        run(str(config_path), dry_run_override=False)

    # Success must not have been recorded (no last-run state written on failure).
    from vault_tier_backup import state
    assert state.read_last_run_time(str(tmp_path / "out")) is None


def test_backup_then_restore_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_ZIP_PASSWORD", PASSWORD)

    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    original_a = source / "book.xlsx"
    original_b = source / "nested" / "db.accdb"
    original_a.write_bytes(b"spreadsheet-payload-\x00\x01\x02")
    original_b.write_bytes(b"access-db-payload-\xff\xfe")

    config_path = _write_config(tmp_path, source)

    # Real run, not dry.
    run(str(config_path), dry_run_override=False)

    zip_path = _find_daily_zip(tmp_path)

    # Encryption is real: wrong password cannot extract.
    with pyzipper.AESZipFile(str(zip_path)) as zf:
        zf.setpassword(b"wrong-password")
        with pytest.raises(Exception):
            zf.extractall(str(tmp_path / "should_fail"))

    # Right password restores byte-for-byte.
    dest = tmp_path / "restored"
    written = restore.restore_archive(str(tmp_path / "out"), zip_path.name, str(dest), PASSWORD)
    assert written

    assert (dest / "book.xlsx").read_bytes() == original_a.read_bytes()
    assert (dest / "nested" / "db.accdb").read_bytes() == original_b.read_bytes()


def test_key_token_created_and_blocks_changed_password(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.xlsx").write_bytes(b"data")
    config_path = _write_config(tmp_path, source)

    monkeypatch.setenv("BACKUP_ZIP_PASSWORD", PASSWORD)
    run(str(config_path), dry_run_override=False)

    # Token now exists for the exe root.
    assert (tmp_path / "out" / keyguard.TOKEN_FILENAME).exists()

    # A changed password must abort before writing anything new.
    monkeypatch.setenv("BACKUP_ZIP_PASSWORD", "a-different-password")
    with pytest.raises(keyguard.PasswordMismatchError):
        run(str(config_path), dry_run_override=False)


def test_restore_wrong_password_raises_clear_error(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.xlsx").write_bytes(b"data")
    config_path = _write_config(tmp_path, source)

    monkeypatch.setenv("BACKUP_ZIP_PASSWORD", PASSWORD)
    run(str(config_path), dry_run_override=False)
    zip_path = _find_daily_zip(tmp_path)

    # restore verifies against the key token first -> PasswordMismatchError,
    # not a cryptic zip failure.
    with pytest.raises(keyguard.PasswordMismatchError):
        restore.restore_archive(str(tmp_path / "out"), zip_path.name, str(tmp_path / "r"), "wrong")
