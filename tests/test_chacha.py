from secrets import randbelow, token_bytes

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers.algorithms import ChaCha20

from randquik import cha


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
        assert ct0.hex() == ct1.hex(), f"{i=} {N=}"


@pytest.mark.parametrize(
    "counter",
    [
        b"\x00\x00\x00\x00\x00\x00\x00\x00",
        b"\xFF\xFF\xFF\xFF\x00\x00\x00\x00",
        b"\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF",
        b"\xFF\xFF\xFF\x7F\xFF\xFF\xFF\xFF",
        b"\x00\x00\x00\x80\xFF\xFF\xFF\xFF",
    ],
)
def test_counter_wrap(counter):
    """Tests carry handling of counter increments"""
    key = bytes(32)
    iv = counter + b"--------"
    c0 = Cipher(ChaCha20(key, iv), None, None).encryptor()
    c1 = cha.Cha(key, iv)
    N = 128
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
        assert ct0.hex() == ct1.hex(), f"{i=} {N=}"


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
