"""Cryptographic functions for key derivation and seed generation."""

import hashlib
import secrets
import string

__all__ = [
    "derive_key",
    "generate_random_seed",
]


def generate_random_seed() -> str:
    """Generate a random alphanumeric seed string."""
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(16))


def derive_key(seed: str, key_bytes: int) -> bytes:
    """Derive a key from a seed string using SHA-512."""
    assert 16 <= key_bytes <= 64, "Only 128-512 bits supported"
    return hashlib.sha512(seed.encode()).digest()[:key_bytes]
