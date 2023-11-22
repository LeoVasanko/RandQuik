#if defined(__x86_64__)
#include <immintrin.h> // AVX2
#include <tmmintrin.h> // SSSE3
#elif defined(__aarch64__)
#include "sse2neon.h"
#endif

#define VEC4_ROT(A, IMM)                                                       \
    _mm_or_si128(_mm_slli_epi32(A, IMM), _mm_srli_epi32(A, (32 - IMM)))

/* same, but replace 2 of the shift/shift/or "rotation" by byte shuffles (8 &
 * 16) (better) */
#define VEC4_QUARTERROUND(A, B, C, D)                                          \
    x_##A = _mm_add_epi32(x_##A, x_##B);                                       \
    t_##A = _mm_xor_si128(x_##D, x_##A);                                       \
    x_##D = _mm_shuffle_epi8(t_##A, rot16);                                    \
    x_##C = _mm_add_epi32(x_##C, x_##D);                                       \
    t_##C = _mm_xor_si128(x_##B, x_##C);                                       \
    x_##B = VEC4_ROT(t_##C, 12);                                               \
    x_##A = _mm_add_epi32(x_##A, x_##B);                                       \
    t_##A = _mm_xor_si128(x_##D, x_##A);                                       \
    x_##D = _mm_shuffle_epi8(t_##A, rot8);                                     \
    x_##C = _mm_add_epi32(x_##C, x_##D);                                       \
    t_##C = _mm_xor_si128(x_##B, x_##C);                                       \
    x_##B = VEC4_ROT(t_##C, 7)

#define ONEQUAD(A, B, C, D, CT)                                                \
    {                                                                          \
        /* Add original block */                                               \
        x_##A = _mm_add_epi32(x_##A, orig##A);                                 \
        x_##B = _mm_add_epi32(x_##B, orig##B);                                 \
        x_##C = _mm_add_epi32(x_##C, orig##C);                                 \
        x_##D = _mm_add_epi32(x_##D, orig##D);                                 \
        /* Transpose */                                                        \
        t_##A = _mm_unpacklo_epi32(x_##A, x_##B);                              \
        t_##B = _mm_unpacklo_epi32(x_##C, x_##D);                              \
        t_##C = _mm_unpackhi_epi32(x_##A, x_##B);                              \
        t_##D = _mm_unpackhi_epi32(x_##C, x_##D);                              \
        x_##A = _mm_unpacklo_epi64(t_##A, t_##B);                              \
        x_##B = _mm_unpackhi_epi64(t_##A, t_##B);                              \
        x_##C = _mm_unpacklo_epi64(t_##C, t_##D);                              \
        x_##D = _mm_unpackhi_epi64(t_##C, t_##D);                              \
                                                                               \
        _mm_storeu_si128((__m128i*)(CT), x_##A);                               \
        _mm_storeu_si128((__m128i*)(CT + 64), x_##B);                          \
        _mm_storeu_si128((__m128i*)(CT + 128), x_##C);                         \
        _mm_storeu_si128((__m128i*)(CT + 192), x_##D);                         \
    }

static inline uint64_t _cha_4block(cha_ctx* ctx, uint8_t* begin, uint8_t* end) {
    if (end - begin < 256)
        return 0;
    uint8_t* c = begin;
    uint32_t* state = ctx->state;

    /* constant for shuffling bytes (replacing multiple-of-8 rotates) */
    const __m128i rot16 =
      _mm_set_epi8(13, 12, 15, 14, 9, 8, 11, 10, 5, 4, 7, 6, 1, 0, 3, 2);
    const __m128i rot8 =
      _mm_set_epi8(14, 13, 12, 15, 10, 9, 8, 11, 6, 5, 4, 7, 2, 1, 0, 3);

    // Load state to vectors, duplicate four times
    __m128i x_0 = _mm_set1_epi32(state[0]);
    __m128i x_1 = _mm_set1_epi32(state[1]);
    __m128i x_2 = _mm_set1_epi32(state[2]);
    __m128i x_3 = _mm_set1_epi32(state[3]);
    __m128i x_4 = _mm_set1_epi32(state[4]);
    __m128i x_5 = _mm_set1_epi32(state[5]);
    __m128i x_6 = _mm_set1_epi32(state[6]);
    __m128i x_7 = _mm_set1_epi32(state[7]);
    __m128i x_8 = _mm_set1_epi32(state[8]);
    __m128i x_9 = _mm_set1_epi32(state[9]);
    __m128i x_10 = _mm_set1_epi32(state[10]);
    __m128i x_11 = _mm_set1_epi32(state[11]);
    __m128i x_12;
    __m128i x_13;
    __m128i x_14 = _mm_set1_epi32(state[14]);
    __m128i x_15 = _mm_set1_epi32(state[15]);
    __m128i orig0 = x_0;
    __m128i orig1 = x_1;
    __m128i orig2 = x_2;
    __m128i orig3 = x_3;
    __m128i orig4 = x_4;
    __m128i orig5 = x_5;
    __m128i orig6 = x_6;
    __m128i orig7 = x_7;
    __m128i orig8 = x_8;
    __m128i orig9 = x_9;
    __m128i orig10 = x_10;
    __m128i orig11 = x_11;
    __m128i orig12 = {};
    __m128i orig13 = {};
    __m128i orig14 = x_14;
    __m128i orig15 = x_15;
    __m128i t_0, t_1, t_2, t_3, t_4, t_5, t_6, t_7, t_8, t_9, t_10, t_11, t_12,
      t_13, t_14, t_15;

    const __m128i addv12 = _mm_set_epi64x(1, 0);
    const __m128i addv13 = _mm_set_epi64x(3, 2);

    while (end - c >= 256) {
        x_0 = orig0;
        x_1 = orig1;
        x_2 = orig2;
        x_3 = orig3;
        x_4 = orig4;
        x_5 = orig5;
        x_6 = orig6;
        x_7 = orig7;
        x_8 = orig8;
        x_9 = orig9;
        x_10 = orig10;
        x_11 = orig11;
        x_14 = orig14;
        x_15 = orig15;

        // Calculate counter + 0..3 for adjacent blocks (x12 low and x13
        // high of each)
        uint32_t in12 = state[12];
        uint32_t in13 = state[13];
        uint64_t in1213 = ((uint64_t)in12) | (((uint64_t)in13) << 32);
        __m128i t12, t13;
        t12 = _mm_set1_epi64x(in1213);
        t13 = _mm_set1_epi64x(in1213);
        x_12 = _mm_add_epi64(addv12, t12);
        x_13 = _mm_add_epi64(addv13, t13);
        t12 = _mm_unpacklo_epi32(x_12, x_13);
        t13 = _mm_unpackhi_epi32(x_12, x_13);
        x_12 = _mm_unpacklo_epi32(t12, t13);
        x_13 = _mm_unpackhi_epi32(t12, t13);
        orig12 = x_12;
        orig13 = x_13;
        in1213 += 4;
        state[12] = in1213 & 0xFFFFFFFF;
        state[13] = (in1213 >> 32) & 0xFFFFFFFF;

        for (int i = 0; i < 10; ++i) {
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

        ONEQUAD(0, 1, 2, 3, c);
        ONEQUAD(4, 5, 6, 7, c + 16);
        ONEQUAD(8, 9, 10, 11, c + 32);
        ONEQUAD(12, 13, 14, 15, c + 48);

        // *counter += 4;
        c += 256;
    }
    return c - begin; // Bytes written
}

#undef ONEQUAD
#undef ONEQUAD_TRANSPOSE
#undef VEC4_ROT
#undef VEC4_QUARTERROUND
#undef VEC4_QUARTERROUND_SHUFFLE
