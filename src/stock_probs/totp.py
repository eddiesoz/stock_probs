"""Bounded RFC 6238 authenticator-app primitives.

The application stores only encrypted TOTP secrets and hashes of recovery codes.  This module
keeps the provider-independent cryptographic operations small enough to audit independently of
the HTTP and persistence layers.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
import time
from datetime import UTC, datetime
from urllib.parse import quote

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_SKEW_STEPS = 1
TOTP_SECRET_BYTES = 20
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_CHARS = 16
_BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_RECOVERY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_KEY_INFO = b"signal-ledger/totp-secret/v1"
_CIPHER_ASSOCIATED_DATA = b"signal-ledger/totp-secret"
_CIPHERTEXT_PREFIX = "v1."


def generate_secret() -> str:
    """Generate one standard Base32 TOTP secret without padding."""

    return base64.b32encode(secrets.token_bytes(TOTP_SECRET_BYTES)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    """Decode a bounded Base32 secret while rejecting ambiguous malformed values."""

    if not isinstance(secret, str) or not 16 <= len(secret) <= 64 or not secret.isascii():
        raise ValueError("invalid TOTP secret")
    normalized = secret.upper().rstrip("=")
    if any(character not in _BASE32_ALPHABET for character in normalized):
        raise ValueError("invalid TOTP secret")
    try:
        decoded = base64.b32decode(normalized + "=" * (-len(normalized) % 8), casefold=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid TOTP secret") from exc
    if len(decoded) < 10 or len(decoded) > 64:
        raise ValueError("invalid TOTP secret")
    return decoded


def _timestamp(now: datetime | None = None) -> int:
    """Return a UTC Unix timestamp for the TOTP time-step calculation."""

    if now is None:
        return int(time.time())
    if now.tzinfo is None:
        raise ValueError("TOTP timestamps must include a timezone")
    return int(now.astimezone(UTC).timestamp())


def time_step(now: datetime | None = None) -> int:
    """Return the RFC 6238 counter for a UTC timestamp."""

    return _timestamp(now) // TOTP_PERIOD_SECONDS


def code_for_step(secret: str, step: int) -> str:
    """Return the six-digit SHA-1 HOTP value for one TOTP time step."""

    if type(step) is not int or step < 0:
        raise ValueError("invalid TOTP time step")
    digest = hmac.new(
        _decode_secret(secret), struct.pack(">Q", step), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % (10**TOTP_DIGITS):0{TOTP_DIGITS}d}"


def matching_step(
    secret: str,
    code: str,
    now: datetime | None = None,
    *,
    skew_steps: int = TOTP_SKEW_STEPS,
) -> int | None:
    """Return the accepted counter for a code, or ``None`` when it is invalid."""

    if (
        type(code) is not str
        or len(code) != TOTP_DIGITS
        or not code.isascii()
        or not code.isdecimal()
        or type(skew_steps) is not int
        or not 0 <= skew_steps <= 2
    ):
        return None
    current = time_step(now)
    for delta in range(-skew_steps, skew_steps + 1):
        candidate = current + delta
        if candidate >= 0 and hmac.compare_digest(code_for_step(secret, candidate), code):
            return candidate
    return None


def normalize_recovery_code(code: str) -> str:
    """Normalize a displayed recovery code to its server-side comparison form."""

    if not isinstance(code, str):
        raise ValueError("invalid recovery code")
    normalized = "".join(code.upper().split()).replace("-", "")
    if len(normalized) != RECOVERY_CODE_CHARS or any(
        character not in _RECOVERY_ALPHABET for character in normalized
    ):
        raise ValueError("invalid recovery code")
    return normalized


def hash_recovery_code(code: str) -> str:
    """Hash one recovery code for durable, one-use storage."""

    normalized = normalize_recovery_code(code)
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Generate bounded, human-enterable single-use recovery codes."""

    if type(count) is not int or not 1 <= count <= 20:
        raise ValueError("recovery code count is out of bounds")
    return [
        "-".join(
            "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(4)) for _ in range(4)
        )
        for _ in range(count)
    ]


def encrypt_secret(secret: str, session_secret: str, *, user_id: int | None = None) -> str:
    """Encrypt a TOTP secret with an installation-derived AES-GCM key."""

    plaintext = _decode_secret(secret)
    key = _derive_key(session_secret)
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _associated_data(user_id))
    encoded = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
    return _CIPHERTEXT_PREFIX + encoded


def decrypt_secret(ciphertext: str, session_secret: str, *, user_id: int | None = None) -> str:
    """Decrypt one stored TOTP secret and validate its Base32 representation."""

    if not isinstance(ciphertext, str) or not ciphertext.startswith(_CIPHERTEXT_PREFIX):
        raise ValueError("invalid encrypted TOTP secret")
    encoded = ciphertext[len(_CIPHERTEXT_PREFIX) :]
    try:
        value = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if not 28 <= len(value) <= 128:
            raise ValueError("invalid encrypted TOTP secret")
        plaintext = AESGCM(_derive_key(session_secret)).decrypt(
            value[:12], value[12:], _associated_data(user_id)
        )
    except (InvalidTag, TypeError, ValueError, UnicodeError, OverflowError) as exc:
        raise ValueError("invalid encrypted TOTP secret") from exc
    secret = base64.b32encode(plaintext).decode("ascii").rstrip("=")
    _decode_secret(secret)
    return secret


def _derive_key(session_secret: str) -> bytes:
    """Derive the factor-encryption key without reusing the raw session secret as a key."""

    if not isinstance(session_secret, str) or len(session_secret.encode("utf-8")) < 32:
        raise ValueError("the session secret is too short for TOTP encryption")
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=_KEY_INFO).derive(
        session_secret.encode("utf-8")
    )


def _associated_data(user_id: int | None) -> bytes:
    """Bind ciphertext to its account so a copied factor cannot cross users."""

    if user_id is None:
        return _CIPHER_ASSOCIATED_DATA
    if type(user_id) is not int or user_id < 1:
        raise ValueError("invalid TOTP account")
    return _CIPHER_ASSOCIATED_DATA + b":" + str(user_id).encode("ascii")


def otpauth_uri(secret: str, account: str, issuer: str = "Signal Ledger") -> str:
    """Build a QR-code-compatible ``otpauth://`` URI with fixed algorithm parameters."""

    _decode_secret(secret)
    safe_account = account.strip() or "Signal Ledger user"
    safe_issuer = issuer.strip() or "Signal Ledger"
    label = f"{safe_issuer}:{safe_account}"
    return (
        "otpauth://totp/"
        + quote(label, safe="")
        + "?secret="
        + quote(secret, safe="")
        + "&issuer="
        + quote(safe_issuer, safe="")
        + "&algorithm=SHA1&digits=6&period=30"
    )
