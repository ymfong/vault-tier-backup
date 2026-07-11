import pytest

from vault_tier_backup import keyguard


def test_verify_returns_true_when_no_token(tmp_path):
    # First run: no token yet, caller is cleared to create one.
    assert keyguard.verify_password(str(tmp_path), "pw") is True


def test_ensure_token_creates_then_matches(tmp_path):
    keyguard.ensure_token(str(tmp_path), "s3cr3t")
    assert (tmp_path / keyguard.TOKEN_FILENAME).exists()
    # Same password verifies fine on subsequent calls.
    assert keyguard.verify_password(str(tmp_path), "s3cr3t") is True


def test_wrong_password_raises(tmp_path):
    keyguard.write_token(str(tmp_path), "right")
    with pytest.raises(keyguard.PasswordMismatchError):
        keyguard.verify_password(str(tmp_path), "wrong")


def test_ensure_token_is_idempotent_and_does_not_overwrite(tmp_path):
    keyguard.ensure_token(str(tmp_path), "pw")
    token_before = (tmp_path / keyguard.TOKEN_FILENAME).read_text()
    keyguard.ensure_token(str(tmp_path), "pw")  # must not rewrite/re-salt
    assert (tmp_path / keyguard.TOKEN_FILENAME).read_text() == token_before


def test_bytes_and_str_passwords_are_equivalent(tmp_path):
    keyguard.write_token(str(tmp_path), "pw")
    assert keyguard.verify_password(str(tmp_path), b"pw") is True
