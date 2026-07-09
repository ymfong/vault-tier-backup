import json
import os
import time
from pathlib import Path

import pytest

from vault_tier_backup import archive
from vault_tier_backup.config import get_required_env, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_get_required_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("BACKUP_TEST_SECRET", raising=False)
    with pytest.raises(EnvironmentError):
        get_required_env("BACKUP_TEST_SECRET")


def test_get_required_env_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("BACKUP_TEST_SECRET", "s3cr3t")
    assert get_required_env("BACKUP_TEST_SECRET") == "s3cr3t"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "does_not_exist.json"))


def test_example_config_uses_correct_monthly_retention_key():
    # Regression test: the key used to be misspelled "delete_old_montly" in the
    # JSON, which never matched archive.py's "delete_old_monthly" lookup, so
    # monthly cleanup silently never ran.
    with open(REPO_ROOT / "config.example.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    assert "delete_old_monthly" in config["control"]
    assert "delete_old_montly" not in config["control"]


def test_delete_old_backups_by_config_honors_monthly_key(tmp_path):
    monthly_dir = tmp_path / "monthly"
    monthly_dir.mkdir()
    old_zip = monthly_dir / "2020-01_monthly.zip"
    old_zip.write_text("data")
    ancient = time.time() - 400 * 86400  # 400 days ago, well past monthly_keep
    os.utime(old_zip, (ancient, ancient))

    config = {
        "control": {"delete_old_monthly": True},
        "backup": {"dual_backup": False},
        "retention": {"monthly_keep": 1},
    }
    roots = {
        "daily_exe": str(tmp_path), "daily_source": str(tmp_path),
        "weekly_exe": str(tmp_path), "weekly_source": str(tmp_path),
        "monthly_exe": str(monthly_dir), "monthly_source": str(monthly_dir),
        "yearly_exe": str(tmp_path), "yearly_source": str(tmp_path),
    }

    archive.delete_old_backups_by_config(config, roots, dry_run=False)

    assert not old_zip.exists()
