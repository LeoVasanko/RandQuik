#if defined(__x86_64__)
#include <emmintrin.h> // SSE2
#include <tmmintrin.h> // SSSE3
#elif defined(__aarch64__)
#include "sse2neon.h"
#endif
#include <stdio.h>
// clang-format off

#define VEC4_ROT(A, IMM)                                                       \
    _mm_or_si128(_mm_slli_epi32(A, IMM), _mm_srli_epi32(A, (32 - IMM)))

/* same, but replace 2 of the shift/shift/or "rotation" by byte shuffles (8 &
 * 16) (better) */
#define VEC4_QUARTERROUND(A, B, C, D)                                          \
    x[A] = _mm_add_epi32(x[A], x[B]);                                          \
    x[D] = _mm_shuffle_epi8(_mm_xor_si128(x[D], x[A]), rot16);                 \
    x[C] = _mm_add_epi32(x[C], x[D]);                                          \
    x[B] = VEC4_ROT(_mm_xor_si128(x[B], x[C]), 12);                            \
    x[A] = _mm_add_epi32(x[A], x[B]);                                          \
    x[D] = _mm_shuffle_epi8(_mm_xor_si128(x[D], x[A]), rot8);                  \
    x[C] = _mm_add_epi32(x[C], x[D]);                                          \
    x[B] = VEC4_ROT(_mm_xor_si128(x[B], x[C]), 7)

#define ONEQUAD(A, B, C, D, OUT)                                                \
    {                                                                          \
        /* Add original block */                                               \
        x[A] = _mm_add_epi32(x[A], orig[A]);                                   \
        x[B] = _mm_add_epi32(x[B], orig[B]);                                   \
        x[C] = _mm_add_epi32(x[C], orig[C]);                                   \
        x[D] = _mm_add_epi32(x[D], orig[D]);                                   \
        /* Transpose */                                                        \
        __m128i abl = _mm_unpacklo_epi32(x[A], x[B]);                          \
        __m128i cdl = _mm_unpacklo_epi32(x[C], x[D]);                          \
        __m128i abh = _mm_unpackhi_epi32(x[A], x[B]);                          \
        __m128i cdh = _mm_unpackhi_epi32(x[C], x[D]);                          \
        x[A] = _mm_unpacklo_epi64(abl, cdl); /* a0 b0 c0 d0 */                 \
        x[B] = _mm_unpackhi_epi64(abl, cdl); /* a1 b1 c1 d1 */                 \
        x[C] = _mm_unpacklo_epi64(abh, cdh); /* a2 b2 c2 d2 */                 \
        x[D] = _mm_unpackhi_epi64(abh, cdh); /* a3 b3 c3 d3 */                 \
        /* Write out 1/4 of each block */                                      \
        _mm_storeu_si128((__m128i*)(OUT), x[A]);                               \
        _mm_storeu_si128((__m128i*)(OUT + 64), x[B]);                          \
        _mm_storeu_si128((__m128i*)(OUT + 128), x[C]);                         \
        _mm_storeu_si128((__m128i*)(OUT + 192), x[D]);                         \
    }

#define COUNTER_INCREMENT(addv)                                                \
    {                                                                          \
        __m128i carry = orig[12];                              \
        orig[12] = _mm_add_epi32(orig[12], addv);                              \
        carry = _mm_srli_epi32(_mm_and_si128(_mm_xor_si128(orig[12], carry), carry), 31); \
        orig[13] = _mm_add_epi32(orig[13], carry);                              \
    }

static inline uint64_t
_cha_4block(uint8_t* buf, size_t bufsize, uint32_t state[16], unsigned rounds) {
    /* constant for shuffling bytes (replacing multiple-of-8 rotates) */
    const __m128i rot16 =
      _mm_set_epi8(13, 12, 15, 14, 9, 8, 11, 10, 5, 4, 7, 6, 1, 0, 3, 2);
    const __m128i rot8 =
      _mm_set_epi8(14, 13, 12, 15, 10, 9, 8, 11, 6, 5, 4, 7, 2, 1, 0, 3);
    // Load state to vectors, duplicate four times, only different counters
    __m128i orig[16];
    for (unsigned i = 0; i < 16; ++i) orig[i] = _mm_set1_epi32(state[i]);
    __m128i addv = _mm_set_epi32(3, 2, 1, 0);
    COUNTER_INCREMENT(addv);
    addv = _mm_set1_epi32(4);
    const unsigned batches = bufsize / 256;
    for (unsigned b = batches; b-->0;) {
        __m128i x[16];
        for (unsigned i = 0; i < 16; ++i) x[i] = orig[i];
        for (unsigned r = rounds / 2; r-->0;) {
            // Mix columns
            VEC4_QUARTERROUND(0, 4, 8, 12);
            VEC4_QUARTERROUND(1, 5, 9, 13);
            VEC4_QUARTERROUND(2, 6, 10, 14);
            VEC4_QUARTERROUND(3, 7, 11, 15);
            // Mix diagonals
            VEC4_QUARTERROUND(0, 5, 10, 15);
            VEC4_QUARTERROUND(1, 6, 11, 12);
            VEC4_QUARTERROUND(2, 7, 8, 13);
            VEC4_QUARTERROUND(3, 4, 9, 14);
        }
        // Add original block, unpack output
        ONEQUAD(0, 1, 2, 3, buf);
        ONEQUAD(4, 5, 6, 7, buf + 16);
        ONEQUAD(8, 9, 10, 11, buf + 32);
        ONEQUAD(12, 13, 14, 15, buf + 48);
        COUNTER_INCREMENT(addv);
        buf += 256;
    }
    // Store counter
    state[12] = _mm_cvtsi128_si32(orig[12]);
    state[13] = _mm_cvtsi128_si32(orig[13]);
    return batches * 256;
}

#undef COUNTER_INCREMENT
#undef ONEQUAD
#undef ONEQUAD_TRANSPOSE
#undef VEC4_ROT
#undef VEC4_QUARTERROUND
#undef VEC4_QUARTERROUND_SHUFFLE
