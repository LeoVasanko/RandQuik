from pathlib import Path
from typing import Any

import cffi

src = Path(__file__).parent.parent / "src"

if not src.is_dir():
    raise RuntimeError("Unable to find RandQuik C sources in {src}")

ffi = cffi.FFI()
ffi.cdef(
    """
    typedef struct cha_ctx { uint32_t input[16]; } cha_ctx;

    int cha_generate(uint8_t* out, uint64_t outlen, const uint8_t key[32], const uint8_t iv[16]);

    void cha_init(cha_ctx* ctx, const uint8_t* key, const uint8_t* iv);
    void cha_wipe(cha_ctx* ctx);
    int cha_update(cha_ctx* ctx, uint8_t* out, uint64_t outlen);
    """
)
lib = ffi.dlopen("../build/librandquik-chacha20.so")


def _processKeys(key, iv):
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")
    if len(iv) != 16:
        raise ValueError(
            "iv must be full 16 bytes, starting with the counter - usually zeroes - followed by nonce"
        )
    return ffi.from_buffer(key), ffi.from_buffer(iv)


def _processBuffer(out):
    if not out:
        raise ValueError("Output buffer of non-zero size is required")
    try:
        outlen = out.nbytes
    except AttributeError:
        out = memoryview(out)
        outlen = out.nbytes
    if getattr(out, "readonly", None):
        raise ValueError("The output buffer must be writable, not e.g. `bytes`")
    return ffi.from_buffer(out), outlen


class Cha:
    def __init__(self, key: bytes | Any, iv: bytes | Any):
        """Construct a generator that holds its internal state, moving forward on each call."""
        key, iv = _processKeys(key, iv)
        self.ctx = ffi.new("cha_ctx*")
        lib.cha_init(self.ctx, key, iv)

    def __del__(self):
        lib.cha_wipe(self.ctx)

    def __call__(self, out: bytearray | Any):
        """Fill the parameter with random bytes"""
        out, outlen = _processBuffer(out)
        lib.cha_update(self.ctx, out, outlen)
        return out


def generate(out: bytearray | Any, key: bytes | Any, iv: bytes | Any):
    """Setup a generator, fill the out buffer and dispose the generator"""
    key, iv =_processKeys(key, iv)
    out, outlen = _processBuffer(out)
    lib.cha_generate(out, outlen, key, iv)
    return out
