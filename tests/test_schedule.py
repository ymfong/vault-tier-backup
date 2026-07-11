"""Scheduling — pure builders run for real; the OS scheduler call is faked so no
task is ever registered on the test machine."""

import os

import pytest

from vault_tier_backup import schedule


def test_backup_command_uses_module_and_abspath():
    cmd = schedule.backup_command("config.json", python_exe="/usr/bin/python")
    assert cmd[0] == "/usr/bin/python"
    assert cmd[1:3] == ["-m", "vault_tier_backup.run"]
    assert "backup" == cmd[-1]
    assert os.path.isabs(cmd[cmd.index("-c") + 1])  # config made absolute


def test_windows_launcher_quotes_spaced_paths():
    content = schedule.windows_launcher_content(
        "C:\\My Data\\config.json", python_exe="C:\\Program Files\\Python\\python.exe"
    )
    assert content.startswith("@echo off")
    assert '"C:\\Program Files\\Python\\python.exe"' in content
    assert '"C:\\My Data\\config.json"' in content


def test_cron_line_maps_time_to_fields():
    line = schedule.cron_line("20:05", "/opt/launcher.sh")
    assert line == "5 20 * * * /opt/launcher.sh"


def test_parse_hhmm_rejects_bad_time():
    with pytest.raises(ValueError):
        schedule._parse_hhmm("25:00")
    with pytest.raises(ValueError):
        schedule._parse_hhmm("noon")


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_install_windows_invokes_schtasks(tmp_path):
    calls = {}

    def fake_runner(argv, **kwargs):
        calls["argv"] = argv
        return _FakeResult(returncode=0, stdout="SUCCESS")

    config = tmp_path / "config.json"
    config.write_text("{}")
    msg = schedule.install_windows(str(config), "20:00", "vtb-test", runner=fake_runner)

    argv = calls["argv"]
    assert argv[0] == "schtasks" and "/Create" in argv
    assert "/TN" in argv and "vtb-test" in argv
    assert "/SC" in argv and "DAILY" in argv
    assert "/ST" in argv and "20:00" in argv
    # Launcher .cmd was written next to the config.
    assert (tmp_path / "vault-tier-backup-run.cmd").exists()
    assert "Scheduled daily backup" in msg


def test_install_windows_raises_on_schtasks_failure(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    fail = lambda argv, **k: _FakeResult(returncode=1, stderr="Access denied")
    with pytest.raises(RuntimeError, match="Access denied"):
        schedule.install_windows(str(config), "20:00", "vtb-test", runner=fail)


def test_uninstall_windows_invokes_delete():
    calls = {}
    def fake_runner(argv, **kwargs):
        calls["argv"] = argv
        return _FakeResult(returncode=0)
    msg = schedule.uninstall_schedule(task_name="vtb-test", runner=fake_runner)
    if os.name == "nt":
        assert "/Delete" in calls["argv"] and "vtb-test" in calls["argv"]
        assert "Removed" in msg
    else:
        assert "crontab" in msg  # POSIX guidance


def test_install_posix_writes_launcher_and_cron(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX path")
    config = tmp_path / "config.json"
    config.write_text("{}")
    msg = schedule.install_posix(str(config), "07:30")
    launcher = tmp_path / "vault-tier-backup-run.sh"
    assert launcher.exists()
    assert os.access(str(launcher), os.X_OK)  # executable bit set
    assert "30 7 * * *" in msg
