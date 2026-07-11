import logging
from datetime import datetime, timedelta

import requests

from vault_tier_backup import monitor, state


def test_staleness_none_when_no_previous_run(tmp_path):
    assert monitor.check_staleness(str(tmp_path), max_quiet_hours=26) is None


def test_staleness_none_when_disabled(tmp_path):
    state.save_last_run_time(str(tmp_path), datetime.now() - timedelta(days=10))
    assert monitor.check_staleness(str(tmp_path), max_quiet_hours=None) is None


def test_staleness_no_warning_when_recent(tmp_path, caplog):
    state.save_last_run_time(str(tmp_path), datetime.now() - timedelta(hours=2))
    with caplog.at_level(logging.WARNING):
        hours = monitor.check_staleness(str(tmp_path), max_quiet_hours=26)
    assert hours < 26
    assert not caplog.records


def test_staleness_warns_when_stale(tmp_path, caplog):
    state.save_last_run_time(str(tmp_path), datetime.now() - timedelta(hours=50))
    with caplog.at_level(logging.WARNING):
        hours = monitor.check_staleness(str(tmp_path), max_quiet_hours=26)
    assert hours > 26
    assert any("silently" in r.message.lower() for r in caplog.records)


def test_heartbeat_skips_when_no_url():
    assert monitor.ping_heartbeat("", "") is False


def test_heartbeat_skips_on_dry_run(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(monitor.requests, "get", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    assert monitor.ping_heartbeat("https://hc.example/abc", "", dry_run=True) is False
    assert called["n"] == 0


def test_heartbeat_success(monkeypatch):
    captured = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        return object()

    monkeypatch.setattr(monitor.requests, "get", fake_get)
    assert monitor.ping_heartbeat("https://hc.example/abc/", "/fail") is True
    assert captured["url"] == "https://hc.example/abc/fail"


def test_heartbeat_swallows_network_error(monkeypatch):
    def boom(url, timeout=None):
        raise requests.RequestException("down")

    monkeypatch.setattr(monitor.requests, "get", boom)
    # Must not raise — monitoring failures never fail the backup.
    assert monitor.ping_heartbeat("https://hc.example/abc", "") is False
