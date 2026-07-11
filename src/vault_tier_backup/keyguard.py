"""Password-loss safeguard.

The encrypted backups are only as recoverable as the password used to create
them. If that password silently changes (a typo in the env var, a new machine,
a rotation) and new backups get written with the new password, the old backups
become unrecoverable AND the folder ends up holding archives with two different
passwords — a quiet, catastrophic failure.

To catch this, the first real backup written to a root drops a small
verification token: a salted PBKDF2 hash of the password (never the password
itself). Every later run and every restore checks the current password against
that token and refuses to proceed on a mismatch, so the problem surfaces
immediately instead of during an emergency restore.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

TOKEN_FILENAME = ".vault_key_check.json"
_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 200_000


class PasswordMismatchError(Exception):
    """Raised when the supplied password does not match the token for a backup root."""


def token_path(backup_root):
    return os.path.join(backup_root, TOKEN_FILENAME)


def _hash_password(password, salt, iterations=_ITERATIONS):
    if isinstance(password, str):
        password = password.encode()
    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations)


def write_token(backup_root, password):
    """Create the verification token for a fresh backup root. Emits a loud
    reminder that losing the password means losing every backup."""
    salt = os.urandom(16)
    digest = _hash_password(password, salt)
    token = {
        "algorithm": _ALGORITHM,
        "iterations": _ITERATIONS,
        "salt": base64.b64encode(salt).decode(),
        "hash": base64.b64encode(digest).decode(),
        "created": datetime.now().isoformat(),
    }
    with open(token_path(backup_root), "w", encoding="utf-8") as f:
        json.dump(token, f, indent=2)

    logger.warning(
        "A new backup password was registered for %s. "
        "STORE THIS PASSWORD SOMEWHERE DURABLE (a password manager, a sealed "
        "note) NOW. If it is lost, every encrypted backup in this location is "
        "permanently unrecoverable — there is no reset.",
        backup_root,
    )


def verify_password(backup_root, password):
    """Check the password against an existing token.

    Returns True if no token exists yet (first run — caller should create one).
    Raises PasswordMismatchError if a token exists and the password doesn't match.
    """
    path = token_path(backup_root)
    if not os.path.exists(path):
        return True

    with open(path, "r", encoding="utf-8") as f:
        token = json.load(f)

    salt = base64.b64decode(token["salt"])
    expected = base64.b64decode(token["hash"])
    actual = _hash_password(password, salt, token.get("iterations", _ITERATIONS))

    # Constant-time comparison to avoid leaking match progress via timing.
    if not hmac.compare_digest(actual, expected):
        raise PasswordMismatchError(
            f"BACKUP_ZIP_PASSWORD does not match the password used for existing "
            f"backups in {backup_root}. Refusing to continue: using a different "
            f"password would create backups you cannot restore alongside the old "
            f"ones. Restore the correct password, or point at a fresh, empty "
            f"backup location."
        )
    return True


def ensure_token(backup_root, password):
    """Verify against an existing token, or create one on first use.

    Raises PasswordMismatchError on mismatch.
    """
    verify_password(backup_root, password)  # raises on mismatch
    if not os.path.exists(token_path(backup_root)):
        write_token(backup_root, password)
