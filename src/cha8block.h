#include <immintrin.h> // AVX2
#include <tmmintrin.h> // SSSE3

#define VEC8_ROT(A, IMM)                                                       \
    _mm256_or_si256(_mm256_slli_epi32(A, IMM), _mm256_srli_epi32(A, (32 - IMM)))

/* same, but replace 2 of the shift/shift/or "rotation" by byte shuffles (8 &
 * 16) (better) */
#define VEC8_QUARTERROUND(A, B, C, D)                                          \
    x[A] = _mm256_add_epi32(x[A], x[B]);                                       \
    t[A] = _mm256_xor_si256(x[D], x[A]);                                       \
    x[D] = _mm256_shuffle_epi8(t[A], rot16);                                   \
    x[C] = _mm256_add_epi32(x[C], x[D]);                                       \
    t[C] = _mm256_xor_si256(x[B], x[C]);                                       \
    x[B] = VEC8_ROT(t[C], 12);                                                 \
    x[A] = _mm256_add_epi32(x[A], x[B]);                                       \
    t[A] = _mm256_xor_si256(x[D], x[A]);                                       \
    x[D] = _mm256_shuffle_epi8(t[A], rot8);                                    \
    x[C] = _mm256_add_epi32(x[C], x[D]);                                       \
    t[C] = _mm256_xor_si256(x[B], x[C]);                                       \
    x[B] = VEC8_ROT(t[C], 7)

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

#define VEC8_ROUND_SEQ(                                                        \
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

#define VEC8_ROUND_HALF(                                                       \
  A1, B1, C1, D1, A2, B2, C2, D2, A3, B3, C3, D3, A4, B4, C4, D4               \
)                                                                              \
    VEC8_LINE1(A1, B1, C1, D1);                                                \
    VEC8_LINE1(A2, B2, C2, D2);                                                \
    VEC8_LINE2(A1, B1, C1, D1);                                                \
    VEC8_LINE2(A2, B2, C2, D2);                                                \
    VEC8_LINE3(A1, B1, C1, D1);                                                \
    VEC8_LINE3(A2, B2, C2, D2);                                                \
    VEC8_LINE4(A1, B1, C1, D1);                                                \
    VEC8_LINE4(A2, B2, C2, D2);                                                \
    VEC8_LINE1(A3, B3, C3, D3);                                                \
    VEC8_LINE1(A4, B4, C4, D4);                                                \
    VEC8_LINE2(A3, B3, C3, D3);                                                \
    VEC8_LINE2(A4, B4, C4, D4);                                                \
    VEC8_LINE3(A3, B3, C3, D3);                                                \
    VEC8_LINE3(A4, B4, C4, D4);                                                \
    VEC8_LINE4(A3, B3, C3, D3);                                                \
    VEC8_LINE4(A4, B4, C4, D4)

#define VEC8_ROUND_HALFANDHALF(                                                \
  A1, B1, C1, D1, A2, B2, C2, D2, A3, B3, C3, D3, A4, B4, C4, D4               \
)                                                                              \
    VEC8_LINE1(A1, B1, C1, D1);                                                \
    VEC8_LINE1(A2, B2, C2, D2);                                                \
    VEC8_LINE2(A1, B1, C1, D1);                                                \
    VEC8_LINE2(A2, B2, C2, D2);                                                \
    VEC8_LINE1(A3, B3, C3, D3);                                                \
    VEC8_LINE1(A4, B4, C4, D4);                                                \
    VEC8_LINE2(A3, B3, C3, D3);                                                \
    VEC8_LINE2(A4, B4, C4, D4);                                                \
    VEC8_LINE3(A1, B1, C1, D1);                                                \
    VEC8_LINE3(A2, B2, C2, D2);                                                \
    VEC8_LINE4(A1, B1, C1, D1);                                                \
    VEC8_LINE4(A2, B2, C2, D2);                                                \
    VEC8_LINE3(A3, B3, C3, D3);                                                \
    VEC8_LINE3(A4, B4, C4, D4);                                                \
    VEC8_LINE4(A3, B3, C3, D3);                                                \
    VEC8_LINE4(A4, B4, C4, D4)

#define VEC8_ROUND(                                                            \
  A1, B1, C1, D1, A2, B2, C2, D2, A3, B3, C3, D3, A4, B4, C4, D4               \
)                                                                              \
    VEC8_ROUND_SEQ(                                                            \
      A1, B1, C1, D1, A2, B2, C2, D2, A3, B3, C3, D3, A4, B4, C4, D4           \
    )

#define ONEQUAD_TRANSPOSE(A, B, C, D)                                          \
    {                                                                          \
        __m128i t0, t1, t2, t3;                                                \
        x[A] = _mm256_add_epi32(x[A], orig[A]);                                \
        x[B] = _mm256_add_epi32(x[B], orig[B]);                                \
        x[C] = _mm256_add_epi32(x[C], orig[C]);                                \
        x[D] = _mm256_add_epi32(x[D], orig[D]);                                \
        t[A] = _mm256_unpacklo_epi32(x[A], x[B]);                              \
        t[B] = _mm256_unpacklo_epi32(x[C], x[D]);                              \
        t[C] = _mm256_unpackhi_epi32(x[A], x[B]);                              \
        t[D] = _mm256_unpackhi_epi32(x[C], x[D]);                              \
        x[A] = _mm256_unpacklo_epi64(t[A], t[B]);                              \
        x[B] = _mm256_unpackhi_epi64(t[A], t[B]);                              \
        x[C] = _mm256_unpacklo_epi64(t[C], t[D]);                              \
        x[D] = _mm256_unpackhi_epi64(t[C], t[D]);                              \
        _mm_storeu_si128(                                                      \
          (__m128i*)(c + 0), _mm256_extracti128_si256(x[A], 0)                 \
        );                                                                     \
        _mm_storeu_si128(                                                      \
          (__m128i*)(c + 64), _mm256_extracti128_si256(x[B], 0)                \
        );                                                                     \
        _mm_storeu_si128(                                                      \
          (__m128i*)(c + 128), _mm256_extracti128_si256(x[C], 0)               \
        );                                                                     \
        _mm_storeu_si128(                                                      \
          (__m128i*)(c + 192), _mm256_extracti128_si256(x[D], 0)               \
        );                                                                     \
        _mm_storeu_si128(                                                      \
          (__m128i*)(c + 256), _mm256_extracti128_si256(x[A], 1)               \
        );                                                                     \
        _mm_storeu_si128(                                                      \
          (__m128i*)(c + 320), _mm256_extracti128_si256(x[B], 1)               \
        );                                                                     \
        _mm_storeu_si128(                                                      \
          (__m128i*)(c + 384), _mm256_extracti128_si256(x[C], 1)               \
        );                                                                     \
        _mm_storeu_si128(                                                      \
          (__m128i*)(c + 448), _mm256_extracti128_si256(x[D], 1)               \
        );                                                                     \
    }

#define ONEQUAD(A, B, C, D) ONEQUAD_TRANSPOSE(A, B, C, D)

#define ONEQUAD_UNPCK(A, B, C, D)                                              \
    {                                                                          \
        x[A] = _mm256_add_epi32(x[A], orig[A]);                                \
        x[B] = _mm256_add_epi32(x[B], orig[B]);                                \
        x[C] = _mm256_add_epi32(x[C], orig[C]);                                \
        x[D] = _mm256_add_epi32(x[D], orig[D]);                                \
        t[A] = _mm256_unpacklo_epi32(x[A], x[B]);                              \
        t[B] = _mm256_unpacklo_epi32(x[C], x[D]);                              \
        t[C] = _mm256_unpackhi_epi32(x[A], x[B]);                              \
        t[D] = _mm256_unpackhi_epi32(x[C], x[D]);                              \
        x[A] = _mm256_unpacklo_epi64(t[A], t[B]);                              \
        x[B] = _mm256_unpackhi_epi64(t[A], t[B]);                              \
        x[C] = _mm256_unpacklo_epi64(t[C], t[D]);                              \
        x[D] = _mm256_unpackhi_epi64(t[C], t[D]);                              \
    }

#define ONEOCTO(A, B, C, D, A2, B2, C2, D2, c)                                 \
    {                                                                          \
        ONEQUAD_UNPCK(A, B, C, D);                                             \
        ONEQUAD_UNPCK(A2, B2, C2, D2);                                         \
        t[A] = _mm256_permute2x128_si256(x[A], x[A2], 0x20);                   \
        t[A2] = _mm256_permute2x128_si256(x[A], x[A2], 0x31);                  \
        t[B] = _mm256_permute2x128_si256(x[B], x[B2], 0x20);                   \
        t[B2] = _mm256_permute2x128_si256(x[B], x[B2], 0x31);                  \
        t[C] = _mm256_permute2x128_si256(x[C], x[C2], 0x20);                   \
        t[C2] = _mm256_permute2x128_si256(x[C], x[C2], 0x31);                  \
        t[D] = _mm256_permute2x128_si256(x[D], x[D2], 0x20);                   \
        t[D2] = _mm256_permute2x128_si256(x[D], x[D2], 0x31);                  \
        _mm256_storeu_si256((__m256i*)(c), t[A]);                              \
        _mm256_storeu_si256((__m256i*)(c + 64), t[B]);                         \
        _mm256_storeu_si256((__m256i*)(c + 128), t[C]);                        \
        _mm256_storeu_si256((__m256i*)(c + 192), t[D]);                        \
        _mm256_storeu_si256((__m256i*)(c + 256), t[A2]);                       \
        _mm256_storeu_si256((__m256i*)(c + 320), t[B2]);                       \
        _mm256_storeu_si256((__m256i*)(c + 384), t[C2]);                       \
        _mm256_storeu_si256((__m256i*)(c + 448), t[D2]);                       \
    }

static inline uint64_t _cha_8block(cha_ctx* ctx, uint8_t* begin, uint8_t* end) {
    if (end - begin < 512)
        return 0;

    uint8_t* c = begin;
    uint32_t* state = ctx->state;
    uint64_t* counter = (uint64_t*)(state + 12);
    /* constant for shuffling bytes (replacing multiple-of-8 rotates) */
    __m256i rot16 = _mm256_set_epi8(
      13, 12, 15, 14, 9, 8, 11, 10, 5, 4, 7, 6, 1, 0, 3, 2, 13, 12, 15, 14, 9,
      8, 11, 10, 5, 4, 7, 6, 1, 0, 3, 2
    );
    __m256i rot8 = _mm256_set_epi8(
      14, 13, 12, 15, 10, 9, 8, 11, 6, 5, 4, 7, 2, 1, 0, 3, 14, 13, 12, 15, 10,
      9, 8, 11, 6, 5, 4, 7, 2, 1, 0, 3
    );

    /* the naive way seems as fast (if not a bit faster) than the vector way */
    __m256i x[16], orig[16], t[16];
    for (int i = 0; i < 16; ++i)
        orig[i] = _mm256_set1_epi32(state[i]);

    const __m256i addv12 = _mm256_set_epi64x(3, 2, 1, 0);
    const __m256i addv13 = _mm256_set_epi64x(7, 6, 5, 4);

    while (end - c >= 512) {
        for (int i = 0; i < 16; ++i)
            if (i != 12 && i != 13)
                x[i] = orig[i];

        // Calculate the eight parallel counters on x_12 and x_13
        t[13] = _mm256_broadcastq_epi64(_mm_cvtsi64_si128(*counter));
        t[12] = _mm256_add_epi64(addv12, t[13]);
        t[13] = _mm256_add_epi64(addv13, t[13]);
        x[12] = _mm256_unpacklo_epi32(t[12], t[13]);
        x[13] = _mm256_unpackhi_epi32(t[12], t[13]);
        t[12] = _mm256_unpacklo_epi32(x[12], x[13]);
        t[13] = _mm256_unpackhi_epi32(x[12], x[13]);

        /* required because unpack* are intra-lane */
        const __m256i permute = _mm256_set_epi32(7, 6, 3, 2, 5, 4, 1, 0);
        x[12] = _mm256_permutevar8x32_epi32(t[12], permute);
        x[13] = _mm256_permutevar8x32_epi32(t[13], permute);

        orig[12] = x[12];
        orig[13] = x[13];

        for (int i = 0; i < 10; ++i) {
            VEC8_ROUND(0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15);
            VEC8_ROUND(0, 5, 10, 15, 1, 6, 11, 12, 2, 7, 8, 13, 3, 4, 9, 14);
        }

        ONEOCTO(0, 1, 2, 3, 4, 5, 6, 7, c);
        ONEOCTO(8, 9, 10, 11, 12, 13, 14, 15, c + 32);

        *counter += 8;
        c += 512;
    }
    return c - begin;
}

#undef ONEQUAD
#undef ONEQUAD_TRANSPOSE
#undef ONEQUAD_UNPCK
#undef ONEOCTO
#undef VEC8_ROT
#undef VEC8_QUARTERROUND
#undef VEC8_QUARTERROUND_NAIVE
#undef VEC8_QUARTERROUND_SHUFFLE
#undef VEC8_QUARTERROUND_SHUFFLE2
#undef VEC8_LINE1
#undef VEC8_LINE2
#undef VEC8_LINE3
#undef VEC8_LINE4
#undef VEC8_ROUND
#undef VEC8_ROUND_SEQ
#undef VEC8_ROUND_HALF
#undef VEC8_ROUND_HALFANDHALF
