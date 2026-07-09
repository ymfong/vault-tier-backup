from vault_tier_backup.run import should_upload_to_cloud


def test_uploads_on_first_of_month_when_enabled():
    assert should_upload_to_cloud(True, day=1, monthly_zip_path_source="x.zip") is True


def test_no_upload_when_disabled():
    assert should_upload_to_cloud(False, day=1, monthly_zip_path_source="x.zip") is False


def test_no_upload_on_non_first_day():
    # Regression test: the original `UPLOAD_TO_CLOUD & today.day == 1` used
    # bitwise `&`, which Python evaluates as `(UPLOAD_TO_CLOUD & today.day) == 1`.
    # With UPLOAD_TO_CLOUD=True (1), that's true on every ODD day of the month,
    # not just the 1st.
    for day in range(2, 32):
        assert should_upload_to_cloud(True, day=day, monthly_zip_path_source="x.zip") is False, (
            f"day {day} incorrectly triggered an upload"
        )


def test_no_upload_when_monthly_zip_not_computed():
    # monthly_zip_path_source is only set when today.day == 1; guards against
    # the NameError the original bug could hit on other odd days.
    assert should_upload_to_cloud(True, day=1, monthly_zip_path_source=None) is False
