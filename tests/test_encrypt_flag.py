"""The encrypt on/off control (backs the GUI's Encrypt toggle).

Default is AES-encrypted. With encrypt=False the archive is a plain zip: readable
without a password, still integrity-checkable, still restorable.
"""

import pyzipper

from vault_tier_backup import archive


def _files(tmp_path):
    p = tmp_path / "book.xlsx"
    p.write_bytes(b"secret-contents-1234")
    return [(str(p), "book.xlsx", p.stat().st_size, 0)]


def test_encrypted_archive_needs_password(tmp_path):
    zp = tmp_path / "enc.zip"
    archive.create_encrypted_zip(_files(tmp_path), str(zp), b"pw", encrypt=True)
    with pyzipper.AESZipFile(str(zp)) as zf:
        zf.setpassword(b"wrong")
        try:
            zf.read("book.xlsx")
            assert False, "wrong password should not decrypt"
        except Exception:
            pass


def test_unencrypted_archive_reads_without_password(tmp_path):
    zp = tmp_path / "plain.zip"
    archive.create_encrypted_zip(_files(tmp_path), str(zp), b"", encrypt=False)
    with pyzipper.AESZipFile(str(zp)) as zf:
        # No setpassword call at all — a plain zip opens directly.
        assert zf.read("book.xlsx") == b"secret-contents-1234"


def test_verify_zip_handles_unencrypted(tmp_path):
    zp = tmp_path / "plain.zip"
    archive.create_encrypted_zip(_files(tmp_path), str(zp), b"", encrypt=False)
    ok, detail = archive.verify_zip(str(zp), b"", expected_count=1, encrypted=False)
    assert ok, detail


def test_unencrypted_members_still_compress(tmp_path):
    # A compressible ordinary file should still deflate when unencrypted.
    big = tmp_path / "data.xlsx"
    big.write_bytes(b"a" * 5000)
    files = [(str(big), "data.xlsx", big.stat().st_size, 0)]
    zp = tmp_path / "plain.zip"
    archive.create_encrypted_zip(files, str(zp), b"", encrypt=False)
    with pyzipper.AESZipFile(str(zp)) as zf:
        info = zf.getinfo("data.xlsx")
        assert info.compress_size < info.file_size
