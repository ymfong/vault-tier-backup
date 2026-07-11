"""Storage growth: don't re-compress already-compressed files.

The tier rollups are zips-of-zips; deflating an already-compressed .zip again
wastes CPU for no gain. Already-compressed formats are stored verbatim
(ZIP_STORED) while ordinary payload files still deflate (ZIP_DEFLATED).
"""

import pyzipper

from vault_tier_backup import archive

PW = b"cmp-pw"


def test_compress_type_selection():
    assert archive._compress_type_for("rollup.zip") == pyzipper.ZIP_STORED
    assert archive._compress_type_for("photo.JPG") == pyzipper.ZIP_STORED  # case-insensitive
    assert archive._compress_type_for("book.xlsx") == pyzipper.ZIP_DEFLATED
    assert archive._compress_type_for("db.accdb") == pyzipper.ZIP_DEFLATED


def test_members_use_expected_compression(tmp_path):
    # One already-compressed file, one ordinary file.
    inner = tmp_path / "2026-07-10_daily.zip"
    inner.write_bytes(b"PK\x03\x04" + b"\x00" * 500)  # zip-ish blob
    book = tmp_path / "book.xlsx"
    book.write_bytes(b"a" * 2000)  # very compressible

    files = [
        (str(inner), inner.name, inner.stat().st_size, 0),
        (str(book), book.name, book.stat().st_size, 0),
    ]
    zip_path = tmp_path / "out.zip"
    archive.create_encrypted_zip(files, str(zip_path), PW)

    with pyzipper.AESZipFile(str(zip_path)) as zf:
        assert zf.getinfo("2026-07-10_daily.zip").compress_type == pyzipper.ZIP_STORED
        assert zf.getinfo("book.xlsx").compress_type == pyzipper.ZIP_DEFLATED


def test_stored_members_still_restore_correctly(tmp_path):
    inner = tmp_path / "inner.zip"
    payload = b"PK\x03\x04" + bytes(range(256)) * 4
    inner.write_bytes(payload)

    files = [(str(inner), "inner.zip", inner.stat().st_size, 0)]
    zip_path = tmp_path / "out.zip"
    archive.create_encrypted_zip(files, str(zip_path), PW)

    # Integrity check passes, and the stored+encrypted bytes round-trip exactly.
    ok, detail = archive.verify_zip(str(zip_path), PW, expected_count=1)
    assert ok, detail
    with pyzipper.AESZipFile(str(zip_path)) as zf:
        zf.setpassword(PW)
        assert zf.read("inner.zip") == payload
