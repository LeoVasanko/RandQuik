#include <stdbool.h>
#include <stdint.h>

#define CHA_BLOCK_SIZE 64

typedef struct cha_ctx {
    uint32_t state[16];
    uint8_t unconsumed[CHA_BLOCK_SIZE];
    uint8_t uncount;
} cha_ctx;

#if defined(__x86_64__)
#ifdef __GNUC__
#pragma GCC target("sse2")
#pragma GCC target("ssse3")
#pragma GCC target("avx2")
#endif
#include "cha8block.h"
#endif

#include "cha1block.h"
#include "cha4block.h"

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <pthread.h>
#include <time.h>
#include <unistd.h>

/// @brief Initialize cha_ctx
/// @param ctx holds ChaCha20 state
/// @param key 32 byte key
/// @param iv 16 bytes, where normally initial 4-8 bytes are zeroes and the rest
/// nonce
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

/// Dispose of sensitive data within the context
void cha_wipe(cha_ctx* ctx);

void cha_wipe(cha_ctx* ctx) { memset(ctx, 0, sizeof(cha_ctx)); }

/// @brief Incremental generation, keeps state between calls
/// @param ctx ChaCha20 context
/// @param out output buffer
/// @param outlen output buffer length
void cha_update(cha_ctx* ctx, uint8_t* out, uint64_t outlen) {
    // The included header will mess with these variables
    uint8_t* c = out;
    uint8_t* end = out + outlen;
    if (ctx->uncount) {
        // Deliver stored bytes first
        uint64_t N = ctx->uncount >= outlen ? outlen : ctx->uncount;
        memcpy(c, ctx->unconsumed, N);
        ctx->uncount -= N;
        c += N;
        if (ctx->uncount) {
            memmove(ctx->unconsumed, ctx->unconsumed + N, ctx->uncount);
        }
        if (c == out + outlen)
            return;
    }
#if defined(__x86_64__)
    // TODO: Handle resume if we are not at block boundary
    if (__builtin_cpu_supports("ssse3")) {
        if (__builtin_cpu_supports("avx2")) {
            c += _cha_8block(ctx, c, end);
            assert(end - c < 512);
        }
        c += _cha_4block(ctx, c, end);
        assert(end - c < 256);
    }
#elif defined(__aarch64__)
    c += _cha_4block(ctx, c, end);
#endif
    c += _cha_block(ctx, c, end);
    assert(c == end);
}

/// @brief Produce a requested number of random bytes of the stream, one shot.
/// @param out output buffer
/// @param outlen output buffer length
/// @param key 32 byte key
/// @param iv 16 bytes, where normally initial 4-8 bytes are zeroes (counter)
void cha_generate(
  uint8_t* out, uint64_t outlen, const uint8_t key[32], const uint8_t iv[16]
) {
    cha_ctx ctx;
    cha_init(&ctx, key, iv);
    cha_update(&ctx, out, outlen);
    cha_wipe(&ctx);
}
