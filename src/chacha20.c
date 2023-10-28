#ifdef __GNUC__
#pragma GCC target("sse2")
#pragma GCC target("ssse3")
#pragma GCC target("avx2")
#endif

#include "chacha20.h"

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <emmintrin.h>
#include <immintrin.h>
#include <pthread.h>
#include <time.h>
#include <tmmintrin.h>
#include <unistd.h>

#include "cha1block.h"
#include "cha4block.h"
#include "cha8block.h"

void cha_init(cha_ctx* ctx, const uint8_t* key, const uint8_t* iv) {
    ctx->state[0] = 0x61707865;
    ctx->state[1] = 0x3320646e;
    ctx->state[2] = 0x79622d32;
    ctx->state[3] = 0x6b206574;
    memcpy(ctx->state + 4, key, 32);
    memcpy(ctx->state + 12, iv, 16);
    memset(ctx->unconsumed, 0, sizeof ctx->unconsumed);
    ctx->uncount = 0;
}

void cha_wipe(cha_ctx* ctx) { memset(ctx, 0, sizeof(cha_ctx)); }

int cha_update(cha_ctx* ctx, uint8_t* out, uint64_t outlen) {
    // The included header will mess with these variables
    uint8_t* c = out;
    uint8_t* end = out + outlen;
    if (ctx->uncount) {
        // Deliver stored bytes first
        uint64_t N = ctx->uncount >= outlen ? outlen : ctx->uncount;
        fprintf(stderr, "%lu, %i, %lu\n", N, ctx->uncount, outlen);
        memcpy(c, ctx->unconsumed, N);
        ctx->uncount -= N;
        c += N;
        if (ctx->uncount) {
            memmove(ctx->unconsumed, ctx->unconsumed + N, ctx->uncount);
        }
        if (c == out + outlen)
            return 0;
    }
    // TODO: Handle resume if we are not at block boundary
    if (__builtin_cpu_supports("ssse3")) {
        if (__builtin_cpu_supports("avx2")) {
            c += _cha_8block(ctx, c, end);
            assert(end - c < 512);
        }
        c += _cha_4block(ctx, c, end);
        assert(end - c < 256);
    }
    c += _cha_block(ctx, c, end);
    assert(c == end);
    return 0;
}

// ChaCha20
int cha_generate(
  uint8_t* out, uint64_t outlen, const uint8_t key[32], const uint8_t iv[16]
) {
    cha_ctx ctx;
    cha_init(&ctx, key, iv);
    cha_update(&ctx, out, outlen);
    cha_wipe(&ctx);
    return 0;
}
