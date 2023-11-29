#include <arm_neon.h>
#include <stdint.h>
#include <stdlib.h>

// clang-format off

#define VEC4_ROT(A, IMM)                                                       \
    vreinterpretq_u32_u8(vorrq_u8(vshlq_n_u32(A, IMM), vshrq_n_u32(A, 32 - IMM)))


/* same, but replace 2 of the shift/shift/or "rotation" by byte shuffles (8 &
 * 16) (better) */
#define VEC4_QUARTERROUND(A, B, C, D)                                          \
    x[A] = vaddq_u32(x[A], x[B]);                                          \
    x[D] = vqtbl1q_u8(veorq_u32(x[D], x[A]), rot16);                 \
    x[C] = vaddq_u32(x[C], x[D]);                                          \
    x[B] = VEC4_ROT(veorq_u32(x[B], x[C]), 12);                            \
    x[A] = vaddq_u32(x[A], x[B]);                                          \
    x[D] = vqtbl1q_u8(veorq_u32(x[D], x[A]), rot8);                  \
    x[C] = vaddq_u32(x[C], x[D]);                                          \
    x[B] = VEC4_ROT(veorq_u32(x[B], x[C]), 7)

#define ONEQUAD(A, B, C, D, OUT)                                                \
    {                                                                          \
        /* Add original block */                                               \
        x[A] = vaddq_u32(x[A], orig[A]);                                   \
        x[B] = vaddq_u32(x[B], orig[B]);                                   \
        x[C] = vaddq_u32(x[C], orig[C]);                                   \
        x[D] = vaddq_u32(x[D], orig[D]);                                   \
        /* Transpose */                                                        \
        uint32x4x2_t ab = vtrnq_u32(x[A], x[B]); \
        uint32x4x2_t cd = vtrnq_u32(x[C], x[D]); \
        x[A] = vcombine_u32(vget_low_u32(ab.val[0]), vget_low_u32(cd.val[0])); \
        x[B] = vcombine_u32(vget_low_u32(ab.val[1]), vget_low_u32(cd.val[1])); \
        x[C] = vcombine_u32(vget_high_u32(ab.val[0]), vget_high_u32(cd.val[0])); \
        x[D] = vcombine_u32(vget_high_u32(ab.val[1]), vget_high_u32(cd.val[1])); \
        /* Write out 1/4 of each block */                                      \
        vst1q_u32((uint32_t*)(OUT), x[A]);                               \
        vst1q_u32((uint32_t*)(OUT + 64), x[B]);                          \
        vst1q_u32((uint32_t*)(OUT + 128), x[C]);                         \
        vst1q_u32((uint32_t*)(OUT + 192), x[D]);                         \
    }

#define COUNTER_INCREMENT(addv)                                          \
    {                                                                     \
        orig[12] = vaddq_u32(orig[12], addv);                              \
        orig[13] = vaddq_u32(orig[13], vshrq_n_u32(vcltq_u32(orig[12], addv), 31)); \
    }

static inline uint64_t
_cha_4block(uint8_t* buf, size_t bufsize, uint32_t state[16], unsigned rounds) {
    /* constant for shuffling bytes (replacing multiple-of-8 rotates) */
    const uint8x16_t rot16 = {
      2, 3, 0, 1,
      6, 7, 4, 5,
      10, 11, 8, 9,
      14, 15, 12, 13
    };
    const uint8x16_t rot8= {
      3, 0, 1, 2,
      7, 4, 5, 6,
      11, 8, 9, 10,
      15, 12, 13, 14
    };
    // Load state to vectors, duplicate four times, only different counters
    uint32x4_t orig[16];
    for (unsigned i = 0; i < 16; ++i) orig[i] = vdupq_n_u32(state[i]);
    uint32x4_t addv = { 0, 1, 2, 3 };
    COUNTER_INCREMENT(addv);
    addv = vdupq_n_u32(4);
    const unsigned batches = bufsize / 256;
    for (unsigned b = batches; b-->0;) {
        uint32x4_t x[16];
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
    state[12] = vgetq_lane_u32(orig[12], 0);
    state[13] = vgetq_lane_u32(orig[13], 0);
    return batches * 256;
}

#undef COUNTER_INCREMENT
#undef ONEQUAD
#undef ONEQUAD_TRANSPOSE
#undef VEC4_ROT
#undef VEC4_QUARTERROUND
#undef VEC4_QUARTERROUND_SHUFFLE
