"""Setup wizard — the pure config-building and password logic (no prompting)."""

import string

from vault_tier_backup import wizard


def test_generate_password_strength():
    pw = wizard.generate_password()
    assert len(pw) == 24
    assert all(c in string.ascii_letters + string.digits for c in pw)
    assert wizard.generate_password() != wizard.generate_password()  # not constant


def test_build_config_minimal_is_valid():
    config = wizard.build_config({"source": "D:\\Data"})
    # Spot-check the shape run() depends on.
    assert config["paths"]["backup_source"] == "D:\\Data"
    # dual_backup must default OFF: a second copy inside the source folder is
    # surprising clutter and doubles storage on the same disk for no safety.
    assert config["backup"]["dual_backup"] is False
    assert config["backup"]["extensions"] == wizard.DEFAULT_EXTENSIONS
    assert config["control"]["dry_run"] is True          # safe default
    assert config["control"]["email_enabled"] is False   # no email given
    assert config["control"]["verify_backups"] is True
    assert config["mirrors"] == []
    assert config["cloud"]["onedrive"]["client_id"]      # placeholder present


def test_build_config_with_email_enables_it():
    config = wizard.build_config({
        "source": "D:\\Data",
        "email": {"method": "smtp", "to": "me@x.com", "from": "me@x.com"},
    })
    assert config["control"]["email_enabled"] is True
    assert config["email"]["to"] == "me@x.com"
    assert config["email"]["method"] == "smtp"


def test_build_config_with_mirrors_and_heartbeat():
    config = wizard.build_config({
        "source": "D:\\Data",
        "mirrors": ["E:\\Bak", "\\\\nas\\bak"],
        "heartbeat_url": "https://hc.example/abc",
        "weekly_day": 0,
    })
    assert config["mirrors"] == ["E:\\Bak", "\\\\nas\\bak"]
    assert config["monitoring"]["heartbeat_url"] == "https://hc.example/abc"
    assert config["backup"]["weekly_day"] == 0


def test_build_config_covers_all_keys_run_reads():
    # Guards against a missing key that would KeyError at runtime.
    config = wizard.build_config({"source": "D:\\Data"})
    for section in ("paths", "backup", "control", "retention", "email", "cloud", "mirrors", "monitoring"):
        assert section in config
    for key in ("daily_keep", "weekly_keep", "monthly_keep", "yearly_keep"):
        assert key in config["retention"]
