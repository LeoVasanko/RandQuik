# The World's Fastest Random Generator

I was disappointed with the sad state of random number generators. Many languages don't ship anything useful and some are stuck with whatever the OS provides. All existing implementations are slow, typically maxing out at a few hundred megabytes per second.

To give some perspective, my tool reaches 37.8 GB/s, writing /dev/null. Several gigabytes per second also on actual SSDs. And this is using full 20 rounds of shuffling.

Secondly, [flaws have been found](https://numpy.org/doc/stable/reference/random/upgrading-pcg64.html) in non-cryptographic algorithms such as the popular Mersenne Twister and PCG64 algorithms.

The cryptographic alternative is simply better, being free of such issues as sequences repeating, and additionally being, well, cryptographically secure. Surprisingly, they appear even to be faster now, so there really ought to be no reason to stick with the old.

We use the widely used encryption algorithm **ChaCha20** as an extremely fast Cryptographically Secure Pseudorandom Number Generator (CSPRNG).

## CLI: randquik

A simple shell tool that simply produces randomness to a file or pipe. It uses ChaCha20 encryption algorithm to produce a random stream that cannot be predicted unless one knows the key - the seed - being used. Keeping always the same seed may be useful for researchers and such who need repeatable results.

<img src="https://github.com/LeoVasanko/RandQuik/blob/legacy/docs/random.webp?raw=true" width="800" alt="Screenshot">

## Installation

Clone the repository, use Meson build:

```
meson setup build
cd build
ninja
sudo ninja install  # optionally
randquik > /dev/null
```

Alternatively you may compile it by hand with `gcc *.c -o randquik -O3 -pthread`.

## Python module

Python module fills any buffers with random data very quickly,

```python
from randquik import Cha, generate
import secrets

key = secrets.token_bytes(32)

# Allocate bytearray and fill with random
data = generate(1_000_000, key)

# Or into an existing buffer
generate_into(data, key)
```

Given the same key, the generate functions will on each call produce the same sequence. For incremental updates, create a generator object and extract as many non-identical bytes from it as needed. Re-initializing with the same key of course once again repeats the requence.

```python
rng = Cha(key)

# Fill some buffer with next bytes iteratively
rng(data)
rng(data)
...
```

## Numpy module

Numpy.Random BitGenerator is also provided for use with Numpy distributions. We do not recommend using it for filling byte buffers, where the Python module and the C code are far faster, but it will still provide better quality random numbers and faster than Numpy's own PCG64.

```python
import numpy as np
from nprand import Cha

gen = np.random.Generator(Cha())   # System random seeding by default
gen.normal(size=10)
```

This module needs to be built by hand with Cython for now. Will be packaged properly in randquik module eventually.

## Tests

Some pytest tests are provided for verifying ChaCha20 implementation correctness against the Cryptography module. Run by `pytest` in the main folder after installation.

## Performance

ChaCha20 as its name implies uses 20 "rounds" of shuffling for each output block. A lower number of rounds can be used for extra performance, where 8 is the minimum that is considered secure, and 12 provides a balanced option, while 20 has comfortable headroom to stay cryptographically secure.

All functions and constructors of this module take `rounds` kwarg for adjusting this. On CLI the equivalent option is `-r`. By default 20 rounds are used.

The CLI uses a configurable number of threads for extremely high performance, while the Python and Numpy modules don't - for now at least.

The implementation is optimized for Apple Silicon SIMD (Neon) and x86 CPUs using AVX2 where available, falling back to SSSE3 and ultimately plain C on other platforms. The implementation is loosely based on code from libsodium but runs faster than the library can.

## Seekability

It is possible to seek ChaCha to any byte position in the stream without delay. This is implemented in C API only for now, and is not exposed via Numpy, Python or CLI interfaces.
