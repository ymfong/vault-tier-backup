"""Backup integrity verification."""

import pyzipper
import pytest

from vault_tier_backup import archive

PW = b"verify-pw"


def _make_zip(tmp_path, names):
    files = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(n.encode() * 10)
        files.append((str(p), n, p.stat().st_size, 0))
    zip_path = tmp_path / "out.zip"
    archive.create_encrypted_zip(files, str(zip_path), PW)
    return zip_path


def test_verify_passes_for_good_archive(tmp_path):
    zip_path = _make_zip(tmp_path, ["a.xlsx", "b.xlsx"])
    ok, detail = archive.verify_zip(str(zip_path), PW, expected_count=2)
    assert ok, detail


def test_verify_fails_on_wrong_count(tmp_path):
    zip_path = _make_zip(tmp_path, ["a.xlsx", "b.xlsx"])
    ok, detail = archive.verify_zip(str(zip_path), PW, expected_count=5)
    assert not ok
    assert "expected 5" in detail


def test_verify_fails_on_corrupted_bytes(tmp_path):
    zip_path = _make_zip(tmp_path, ["a.xlsx", "b.xlsx"])
    # Corrupt the middle of the file so a member's CRC/decryption breaks.
    data = bytearray(zip_path.read_bytes())
    for i in range(len(data) // 3, len(data) // 3 + 40):
        data[i] ^= 0xFF
    zip_path.write_bytes(bytes(data))

    ok, detail = archive.verify_zip(str(zip_path), PW)
    assert not ok, "corruption should have been detected"


def test_verify_fails_on_truncated_file(tmp_path):
    zip_path = _make_zip(tmp_path, ["a.xlsx", "b.xlsx"])
    data = zip_path.read_bytes()
    zip_path.write_bytes(data[: len(data) // 2])  # truncate

    ok, detail = archive.verify_zip(str(zip_path), PW)
    assert not ok


def test_verify_string_password_equivalent(tmp_path):
    zip_path = _make_zip(tmp_path, ["a.xlsx"])
    ok, _ = archive.verify_zip(str(zip_path), "verify-pw", expected_count=1)
    assert ok
