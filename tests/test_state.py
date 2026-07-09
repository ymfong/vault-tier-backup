from datetime import datetime

from vault_tier_backup import state


def test_determine_backup_type_matches_weekly_day():
    sunday = datetime(2026, 7, 12)  # a Sunday
    assert sunday.weekday() == 6
    assert state.determine_backup_type(sunday, weekly_day=6) == "weekly"
    assert state.determine_backup_type(sunday, weekly_day=0) == "daily"


def test_days_limit_is_none_on_weekly_day_with_full_backup(tmp_path):
    # Regression test for the ordering bug: backup_type must be computed
    # before days_limit, otherwise weekly_full_backup never takes effect.
    backup_type = state.determine_backup_type(datetime(2026, 7, 12), weekly_day=6)
    days_limit = state.determine_days_limit(
        backup_type, weekly_full_backup=True, backup_root_exe=str(tmp_path), max_age_days=1
    )
    assert backup_type == "weekly"
    assert days_limit is None


def test_days_limit_falls_back_to_max_age_on_non_weekly_day(tmp_path):
    backup_type = state.determine_backup_type(datetime(2026, 7, 13), weekly_day=6)  # Monday
    days_limit = state.determine_days_limit(
        backup_type, weekly_full_backup=True, backup_root_exe=str(tmp_path), max_age_days=1
    )
    assert backup_type == "daily"
    assert days_limit == 1  # no .last_backup_time file yet -> default_days


def test_days_limit_ignores_weekly_full_backup_when_disabled(tmp_path):
    backup_type = state.determine_backup_type(datetime(2026, 7, 12), weekly_day=6)
    days_limit = state.determine_days_limit(
        backup_type, weekly_full_backup=False, backup_root_exe=str(tmp_path), max_age_days=1
    )
    assert backup_type == "weekly"
    assert days_limit == 1
