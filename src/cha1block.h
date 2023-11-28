#include <stdint.h>
#include <string.h>

// clang-format off
#define QUARTERSTEP(a, b, c, n) a += b; c ^= a; c = (c << n) | (c >> (32 - n))
#define QUARTERROUND(a, b, c, d) {\
    QUARTERSTEP(a, b, d, 16); QUARTERSTEP(c, d, b, 12); \
    QUARTERSTEP(a, b, d, 8);  QUARTERSTEP(c, d, b, 7); }

static inline uint64_t _cha_block(uint8_t out[CHA_BLOCK_SIZE], uint32_t state[16], unsigned rounds) {
    uint32_t x[16];
    for (unsigned i = 0; i < 16; ++i) x[i] = state[i];  // Faster than memcpy
    for (unsigned i = rounds / 2; i-->0;) {
        // Mix columns, then diagonals
        for (unsigned j = 0; j < 4; ++j) QUARTERROUND(x[j], x[4 + j], x[8 + j], x[12 + j]);
        for (unsigned j = 0; j < 4; ++j) QUARTERROUND(x[j], x[4 + (j+1)%4], x[8 + (j+2)%4], x[12 + (j+3)%4]);
    }
    uint32_t* buf = (uint32_t*)out;
    for (unsigned i = 0; i < 16; ++i) buf[i] = x[i] + state[i];
    memset(x, 0, sizeof x);
    ++*(uint64_t*)(state + 12); // Increment counter
    return CHA_BLOCK_SIZE;
}

#undef QUARTERROUND
#undef QUARTERSTEP
