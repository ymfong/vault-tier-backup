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


def test_backup_command_frozen_exe_takes_args_directly(monkeypatch):
    import sys
    # In a PyInstaller build the exe IS the program — no `-m` module flag.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:\\Apps\\VaultTierBackup.exe")
    cmd = schedule.backup_command("config.json")
    assert cmd[0] == "C:\\Apps\\VaultTierBackup.exe"
    assert "-m" not in cmd
    assert cmd[-1] == "backup" and "-c" in cmd


def test_quote_wraps_paths_with_spaces_or_backslashes():
    assert schedule._quote("C:\\My Data\\x") == '"C:\\My Data\\x"'
    assert schedule._quote("has space") == '"has space"'
    assert schedule._quote("plain") == "plain"


def test_windows_launcher_structure_and_quoting():
    # abspath() would rewrite a foreign Windows path on non-Windows runners, so
    # assert on the stable parts and on the (spaced) python exe being quoted.
    content = schedule.windows_launcher_content(
        "config.json", python_exe="C:\\Program Files\\Python\\python.exe"
    )
    assert content.startswith("@echo off\r\n")
    assert content.rstrip().endswith("backup")
    assert '"C:\\Program Files\\Python\\python.exe"' in content
    assert "-m vault_tier_backup.run" in content


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


def test_task_xml_survives_missed_runs():
    xml = schedule.windows_task_xml("C:\\x\\run.cmd", "20:00")
    # The whole point of #5: a missed run must catch up, and it wakes to run.
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml
    assert "<WakeToRun>true</WakeToRun>" in xml
    # Runs as the logged-in user (so the per-user password env var is visible).
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert "<Command>C:\\x\\run.cmd</Command>" in xml
    assert "T20:00:00" in xml


def test_install_windows_registers_from_xml(tmp_path):
    calls = {}

    def fake_runner(argv, **kwargs):
        calls["argv"] = argv
        # The XML file must still exist at call time so schtasks could read it.
        xml_path = argv[argv.index("/XML") + 1]
        with open(xml_path, encoding="utf-16") as f:
            calls["xml"] = f.read()
        return _FakeResult(returncode=0, stdout="SUCCESS")

    config = tmp_path / "config.json"
    config.write_text("{}")
    msg = schedule.install_windows(str(config), "20:00", "vtb-test", runner=fake_runner)

    argv = calls["argv"]
    assert argv[0] == "schtasks" and "/Create" in argv
    assert "/TN" in argv and "vtb-test" in argv
    assert "/XML" in argv and "/F" in argv
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in calls["xml"]
    # Launcher .cmd was written next to the config; temp XML is cleaned up.
    assert (tmp_path / "vault-tier-backup-run.cmd").exists()
    assert "catch up" in msg


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
