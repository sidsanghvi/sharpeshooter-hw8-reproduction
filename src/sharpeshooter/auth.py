"""One-way credential storage. No authentication material is logged."""
import hashlib
import hmac
import secrets


def hash_key(plaintext: str, salt: str) -> str:
    return hashlib.scrypt(plaintext.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32).hex()


def new_key():
    prefix = secrets.token_hex(6)
    plaintext = f"ss_{prefix}_{secrets.token_urlsafe(32)}"
    salt = secrets.token_hex(16)
    return plaintext, prefix, salt, hash_key(plaintext, salt)


def matches_key(plaintext: str, salt: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_key(plaintext, salt), expected_hash)


def hash_claim_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate_bearer(ledger, authorization):
    """Authenticate before reading a tool body; audit only stable reason codes."""
    from .errors import DomainError

    if authorization is None:
        with ledger.action("transport.authenticate", None):
            raise DomainError("AUTH_REQUIRED", "Bearer authentication is required")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        with ledger.action("transport.authenticate", None):
            raise DomainError("AUTH_INVALID", "Invalid bearer authentication")
    return ledger.authenticate(parts[1])
