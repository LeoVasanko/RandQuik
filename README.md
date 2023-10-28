# Extremely fast Cryptographically Secure PRNG

I was disappointed with the sad state of random number generators. Many languages don't ship anything useful and some are stuck with whatever the OS provides. All existing implementations are slow, typically maxing out at a few hundred megabytes per second.

To give some perspective, my tool reaches 37.8 GB/s, writing /dev/null. Several gigabytes per second also on actual SSDs.

Secondly, flaws have been found in non-cryptographic algorithms, especially on Mersenne Twister. The cryptographic options are simply better, being free of such issues as sequences repeating, and additionally being, well, cryptographically secure. Surprisingly, they appear even to be faster now, so there really ought to be no reason to stick with the old.

## CLI: randquik

A simple shell tool that simply produces randomness to a file or pipe. It uses ChaCha20 encryption algorithm to produce a random stream that cannot be predicted unless one knows the key - the seed - being used. Keeping always the same seed may be useful for researchers and such who need repatable results.

<img src="https://github.com/LeoVasanko/RandQuik/blob/main/docs/random.webp?raw=true" width="800" alt="Screenshot">

## Installation

Clone the repository, use Meson build:

```
meson setup build
cd build
ninja
./randquik
```

Alternatively you may compile it by hand with `gcc randquik.c -o randquik -O3 -pthread`.

## Python module

I have a Python binding to this in the works, with the intention of being able to use these faster random numbers also for creating byte buffers and with numpy.random there.
