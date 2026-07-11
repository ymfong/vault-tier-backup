"""Open/locked-file resilience.

A file locked by Excel/Access (Windows raises PermissionError, "file in use")
must be skipped with a warning — never abandon the whole archive — and transient
locks should be retried. These tests simulate locks deterministically by making
one file's write raise, so they run identically on every platform.
"""

import pyzipper

from vault_tier_backup import archive


def _files(tmp_path, names):
    out = []
    for name in names:
        p = tmp_path / name
        p.write_bytes(name.encode())
        out.append((str(p), name, p.stat().st_size, 0))
    return out


def _patch_write_to_lock(monkeypatch, locked_name, fail_times=None):
    """Make zipf.write raise PermissionError for locked_name — permanently if
    fail_times is None, otherwise only the first fail_times attempts."""
    real_write = pyzipper.AESZipFile.write
    state = {"n": 0}

    def fake_write(self, filename, arcname=None, *a, **k):
        if arcname == locked_name:
            state["n"] += 1
            if fail_times is None or state["n"] <= fail_times:
                raise PermissionError(f"[WinError 32] file in use: {arcname}")
        return real_write(self, filename, arcname, *a, **k)

    monkeypatch.setattr(pyzipper.AESZipFile, "write", fake_write)


def test_locked_file_is_skipped_others_succeed(tmp_path, monkeypatch):
    files = _files(tmp_path, ["a.xlsx", "locked.xlsx", "c.xlsx"])
    _patch_write_to_lock(monkeypatch, "locked.xlsx")  # never frees

    skipped = []
    zip_path = tmp_path / "out.zip"
    total = archive.create_encrypted_zip(
        files, str(zip_path), b"pw", skipped=skipped, retries=1, retry_delay=0
    )

    # The archive still exists and holds the two readable files.
    assert zip_path.exists()
    with pyzipper.AESZipFile(str(zip_path)) as zf:
        names = set(zf.namelist())
    assert names == {"a.xlsx", "c.xlsx"}
    assert [rel for rel, _ in skipped] == ["locked.xlsx"]
    assert total == len(b"a.xlsx") + len(b"c.xlsx")


def test_transient_lock_is_retried_then_succeeds(tmp_path, monkeypatch):
    files = _files(tmp_path, ["a.xlsx", "busy.xlsx"])
    _patch_write_to_lock(monkeypatch, "busy.xlsx", fail_times=1)  # frees on retry

    skipped = []
    zip_path = tmp_path / "out.zip"
    archive.create_encrypted_zip(
        files, str(zip_path), b"pw", skipped=skipped, retries=2, retry_delay=0
    )

    with pyzipper.AESZipFile(str(zip_path)) as zf:
        names = set(zf.namelist())
    assert names == {"a.xlsx", "busy.xlsx"}  # retry recovered it
    assert skipped == []


def test_skipped_list_is_optional(tmp_path, monkeypatch):
    files = _files(tmp_path, ["a.xlsx", "locked.xlsx"])
    _patch_write_to_lock(monkeypatch, "locked.xlsx")

    zip_path = tmp_path / "out.zip"
    # No skipped list passed — must not blow up, still completes the rest.
    archive.create_encrypted_zip(files, str(zip_path), b"pw", retries=0, retry_delay=0)

    with pyzipper.AESZipFile(str(zip_path)) as zf:
        assert zf.namelist() == ["a.xlsx"]
