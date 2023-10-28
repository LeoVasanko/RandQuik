#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define QUARTERSTEP(a, b, c, n)                                                \
    a += b;                                                                    \
    c ^= a;                                                                    \
    c = (c << n) | (c >> (32 - n))

#define QUARTERROUND(a, b, c, d)                                               \
    QUARTERSTEP(a, b, d, 16);                                                  \
    QUARTERSTEP(c, d, b, 12);                                                  \
    QUARTERSTEP(a, b, d, 8);                                                   \
    QUARTERSTEP(c, d, b, 7);

static inline uint64_t
_cha_block(uint32_t* state, uint8_t* begin, uint8_t* end) {
    uint64_t* counter = (uint64_t*)&state[12];
    uint8_t* c = begin;
    while (c < end) {
        uint32_t x[16];
        memcpy(x, state, sizeof x);
        for (int i = 20; i > 0; i -= 2) {
            QUARTERROUND(x[0], x[4], x[8], x[12])
            QUARTERROUND(x[1], x[5], x[9], x[13])
            QUARTERROUND(x[2], x[6], x[10], x[14])
            QUARTERROUND(x[3], x[7], x[11], x[15])
            QUARTERROUND(x[0], x[5], x[10], x[15])
            QUARTERROUND(x[1], x[6], x[11], x[12])
            QUARTERROUND(x[2], x[7], x[8], x[13])
            QUARTERROUND(x[3], x[4], x[9], x[14])
        }
        for (int i = 0; i < 16; i++)
            x[i] += state[i];

        ++*counter;

        uint64_t bytes = end - c;
        if (bytes < 64) {
            memcpy(c, x, bytes);
            c = end;
            break;
        }
        memcpy(c, x, 64);
        c += 64;
    }
    return c - begin;
}
