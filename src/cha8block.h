#include <immintrin.h> // AVX2
#include <tmmintrin.h> // SSSE3

// clang-format off

#define VEC8_ROT(A, IMM)                                                       \
    _mm256_or_si256(_mm256_slli_epi32(A, IMM), _mm256_srli_epi32(A, (32 - IMM)))

#define VEC8_LINE1(A, B, C, D)                                                 \
    x[A] = _mm256_add_epi32(x[A], x[B]);                                       \
    x[D] = _mm256_shuffle_epi8(_mm256_xor_si256(x[D], x[A]), rot16)
#define VEC8_LINE2(A, B, C, D)                                                 \
    x[C] = _mm256_add_epi32(x[C], x[D]);                                       \
    x[B] = VEC8_ROT(_mm256_xor_si256(x[B], x[C]), 12)
#define VEC8_LINE3(A, B, C, D)                                                 \
    x[A] = _mm256_add_epi32(x[A], x[B]);                                       \
    x[D] = _mm256_shuffle_epi8(_mm256_xor_si256(x[D], x[A]), rot8)
#define VEC8_LINE4(A, B, C, D)                                                 \
    x[C] = _mm256_add_epi32(x[C], x[D]);                                       \
    x[B] = VEC8_ROT(_mm256_xor_si256(x[B], x[C]), 7)

#define VEC8_ROUND(                                                            \
  A1, B1, C1, D1, A2, B2, C2, D2, A3, B3, C3, D3, A4, B4, C4, D4               \
)                                                                              \
    VEC8_LINE1(A1, B1, C1, D1);                                                \
    VEC8_LINE1(A2, B2, C2, D2);                                                \
    VEC8_LINE1(A3, B3, C3, D3);                                                \
    VEC8_LINE1(A4, B4, C4, D4);                                                \
    VEC8_LINE2(A1, B1, C1, D1);                                                \
    VEC8_LINE2(A2, B2, C2, D2);                                                \
    VEC8_LINE2(A3, B3, C3, D3);                                                \
    VEC8_LINE2(A4, B4, C4, D4);                                                \
    VEC8_LINE3(A1, B1, C1, D1);                                                \
    VEC8_LINE3(A2, B2, C2, D2);                                                \
    VEC8_LINE3(A3, B3, C3, D3);                                                \
    VEC8_LINE3(A4, B4, C4, D4);                                                \
    VEC8_LINE4(A1, B1, C1, D1);                                                \
    VEC8_LINE4(A2, B2, C2, D2);                                                \
    VEC8_LINE4(A3, B3, C3, D3);                                                \
    VEC8_LINE4(A4, B4, C4, D4)

#define TRANSPOSE(A, B, C, D)                                                  \
    {                                                                          \
        const __m256i t0 = _mm256_unpacklo_epi32(x[A], x[B]),                  \
                      t1 = _mm256_unpacklo_epi32(x[C], x[D]),                  \
                      t2 = _mm256_unpackhi_epi32(x[A], x[B]),                  \
                      t3 = _mm256_unpackhi_epi32(x[C], x[D]);                  \
        x[A] = _mm256_unpacklo_epi64(t0, t1);                                  \
        x[B] = _mm256_unpackhi_epi64(t0, t1);                                  \
        x[C] = _mm256_unpacklo_epi64(t2, t3);                                  \
        x[D] = _mm256_unpackhi_epi64(t2, t3);                                  \
    }

#define ONEOCTO(A, B, C, D, A2, B2, C2, D2, c)                                 \
    {                                                                          \
        TRANSPOSE(A, B, C, D);                                             \
        TRANSPOSE(A2, B2, C2, D2);                                         \
        _mm256_storeu_si256((__m256i*)(c), _mm256_permute2x128_si256(x[A], x[A2], 0x20));                              \
        _mm256_storeu_si256((__m256i*)(c + 64), _mm256_permute2x128_si256(x[B], x[B2], 0x20));                         \
        _mm256_storeu_si256((__m256i*)(c + 128), _mm256_permute2x128_si256(x[C], x[C2], 0x20));                        \
        _mm256_storeu_si256((__m256i*)(c + 192), _mm256_permute2x128_si256(x[D], x[D2], 0x20));                        \
        _mm256_storeu_si256((__m256i*)(c + 256), _mm256_permute2x128_si256(x[A], x[A2], 0x31));                       \
        _mm256_storeu_si256((__m256i*)(c + 320), _mm256_permute2x128_si256(x[B], x[B2], 0x31));                       \
        _mm256_storeu_si256((__m256i*)(c + 384), _mm256_permute2x128_si256(x[C], x[C2], 0x31));                       \
        _mm256_storeu_si256((__m256i*)(c + 448), _mm256_permute2x128_si256(x[D], x[D2], 0x31));                       \
    }

#define COUNTER_INCREMENT(addv)                              \
    {                                                                          \
        orig[12] = _mm256_add_epi32(orig[12], addv);                           \
        orig[13] = _mm256_add_epi32(orig[13], _mm256_srli_epi32(_mm256_cmpgt_epi32(addv, orig[12]), 31));                           \
    }

static inline uint64_t
_cha_8block(uint8_t* buf, size_t bufsize, uint32_t state[16], unsigned rounds) {
    unsigned batches = bufsize / 512;
    /* constant for shuffling bytes (replacing multiple-of-8 rotates) */
    const __m256i rot16 = _mm256_set_epi8(
      13, 12, 15, 14,
      9, 8, 11, 10,
      5, 4, 7, 6,
      1, 0, 3, 2,
      13, 12, 15, 14,
      9, 8, 11, 10,
      5, 4, 7, 6,
      1, 0, 3, 2
    );
    const __m256i rot8 = _mm256_set_epi8(
      14, 13, 12, 15,
      10, 9, 8, 11,
      6, 5, 4, 7,
      2, 1, 0, 3,
      14, 13, 12, 15,
      10, 9, 8, 11,
      6, 5, 4, 7,
      2, 1, 0, 3
    );
    __m256i orig[16];
    for (int i = 0; i < 16; ++i)
        orig[i] = _mm256_set1_epi32(state[i]);
    COUNTER_INCREMENT(_mm256_set_epi32(7, 6, 5, 4, 3, 2, 1, 0));

    for (unsigned b = batches; b-->0;) {
        __m256i x[16];
        for (int i = 0; i < 16; ++i) x[i] = orig[i];
        for (unsigned r = rounds / 2; r-->0;) {
            VEC8_ROUND(0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15);
            VEC8_ROUND(0, 5, 10, 15, 1, 6, 11, 12, 2, 7, 8, 13, 3, 4, 9, 14);
        }
        for (unsigned i = 0; i < 16; ++i) x[i] = _mm256_add_epi32(x[i], orig[i]);
        ONEOCTO(0, 1, 2, 3, 4, 5, 6, 7, buf);
        ONEOCTO(8, 9, 10, 11, 12, 13, 14, 15, buf + 32);
        COUNTER_INCREMENT(_mm256_set1_epi32(8));
        buf += 512;
    }
    state[12] = _mm256_extract_epi32(orig[12], 0);
    state[13] = _mm256_extract_epi32(orig[13], 0);
    return batches * 512;
}

#undef COUNTER_INCREMENT
#undef ONEOCTO
#undef TRANSPOSE
#undef VEC8_ROT
#undef VEC8_LINE1
#undef VEC8_LINE2
#undef VEC8_LINE3
#undef VEC8_LINE4
#undef VEC8_ROUND
