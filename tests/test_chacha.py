from secrets import randbelow, token_bytes

import numpy as np
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers.algorithms import ChaCha20
from scipy.stats import chisquare

from randquik import cha


def test_cha_generate_statistical():
    """Requests in multiple of ChaCha20 block size 64 bytes"""
    ROUNDS = 100
    min_p = 1 - 0.99 ** (1 / ROUNDS)  # 99 % confidence over the entire test
    print(min_p)

    for round in range(ROUNDS):
        # First round both zero, use 8-byte nonce as round counter
        key = bytes(32)
        nonce = round.to_bytes(8, "little")
        iv = bytes(8) + nonce  # Cryptography module requires IV (counter, nonce)
        # Varying sizes to test internal processing that occurs in 64 bit blocks
        # and with SIMD implementations also 256 or 512 bytes at a time.
        N = 10000 + randbelow(10000)
        ct0, ct1 = bytearray(N), bytearray(N)
        Cipher(ChaCha20(key, iv), None, None).encryptor().update_into(bytes(N), ct0)
        cha.generate(ct1, key, nonce)
        assert len(ct0) == len(ct1)
        assert ct0.hex() == ct1.hex()
        assert ct1.count(0)

        # Zeroing out 50 bytes fail the test in ~30 rounds
        # ct1[:50] = bytes(50)

        # Test that all byte values are equivalently common (despite zero inputs)
        observed = np.bincount(ct1, minlength=256)
        expected = np.full(256, N / 256)
        chi2, p_value = chisquare(observed, expected)
        assert p_value >= min_p, f"{round=} {N=}"


def test_cipherstreams_fullblocks():
    """Requests in multiple of ChaCha20 block size 64 bytes"""
    key = token_bytes(32)
    iv = token_bytes(16)
    c0 = Cipher(ChaCha20(key, iv), None, None).encryptor()
    c1 = cha.Cha(key, iv)

    for i in range(2048):
        N = 64 * (1 + randbelow(2048))
        ct0 = c0.update(bytes(N))
        ct1 = c1(bytearray(N))
        assert len(ct0) == len(ct1)
        assert ct0.hex() == ct1.hex()


def test_cipherstreams_partial_updates():
    """Odd-sized requests that retain leftover buffers"""
    key = token_bytes(32)
    iv = token_bytes(16)
    c0 = Cipher(ChaCha20(key, iv), None, None).encryptor()
    c1 = cha.Cha(key, iv)

    for i in range(2048):
        N = 1 + randbelow(2048)
        ct0 = c0.update(bytes(N))
        ct1 = c1(bytearray(N))
        assert len(ct0) == len(ct1)
        assert ct0.hex() == ct1.hex()


def test_cipherstreams_32leftover():
    """Test the special case where the second response comes entirely from the leftover buffer"""
    key = token_bytes(32)
    nonce = token_bytes(12)  # IETF nonce size
    iv = bytes(4) + nonce
    c0 = Cipher(ChaCha20(key, iv), None, None).encryptor()
    c1 = cha.Cha(key, nonce)

    for N in [512 - 32, 32]:
        ct0 = c0.update(bytes(N))
        ct1 = c1(bytearray(N))
        assert len(ct0) == len(ct1)
        assert ct0.hex() == ct1.hex()
