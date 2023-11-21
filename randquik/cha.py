import sys
from pathlib import Path
from typing import Any

import cffi

src = Path(__file__).parent.parent / "src"

if not src.is_dir():
    raise RuntimeError("Unable to find RandQuik C sources in {src}")

ffi = cffi.FFI()
ffi.cdef(
    """
    typedef struct cha_ctx {
        uint32_t input[16];
        uint8_t unconsumed[64];
        uint8_t uncount;
    } cha_ctx;

    int cha_generate(uint8_t* out, uint64_t outlen, const uint8_t key[32], const uint8_t iv[16]);

    void cha_init(cha_ctx* ctx, const uint8_t* key, const uint8_t* iv);
    void cha_wipe(cha_ctx* ctx);
    int cha_update(cha_ctx* ctx, uint8_t* out, uint64_t outlen);
    """
)
libname = "librandquik-chacha20.so"
if sys.platform == "darwin":
    libname = "librandquik-chacha20.dylib"
elif sys.platform == "win32":
    libname = "randquik-chacha20.dll"
lib = ffi.dlopen((Path(__file__).parent.parent / f"build/{libname}").as_posix())


def _processKeys(key, iv):
    key = memoryview(key)
    iv = memoryview(iv)
    if key.nbytes != 32:
        raise ValueError("key must be 32 bytes")
    if iv.nbytes != 16:
        # Allow original and IETF nonces with zero counter
        if iv.nbytes == 8:
            iv = bytes(8) + iv
        elif iv.nbytes == 12:
            iv = bytes(4) + iv
        else:
            raise ValueError(
                "iv lenth must be 8 (original nonce), 12 (IETF) or 16 (counter in initial 8 bytes)"
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
        outbuf, outlen = _processBuffer(out)
        lib.cha_update(self.ctx, outbuf, outlen)
        return out


def generate(out: bytearray | Any, key: bytes | Any, iv: bytes | Any):
    """Setup a generator, fill the out buffer and dispose the generator"""
    key, iv = _processKeys(key, iv)
    outbuf, outlen = _processBuffer(out)
    lib.cha_generate(outbuf, outlen, key, iv)
    return out
