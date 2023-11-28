#include <stdbool.h>
#include <stdint.h>

#define CHA_BLOCK_SIZE 64
#define BATCH_BLOCKS 8
#define BATCH_SIZE (BATCH_BLOCKS * CHA_BLOCK_SIZE)

#if defined(__x86_64__)
#ifdef __GNUC__
#pragma GCC target("sse2")
#pragma GCC target("ssse3")
#pragma GCC target("avx2")
#endif
#include "cha8block.h"
#else
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

typedef struct cha_ctx {
    uint32_t state[16];
    uint8_t unconsumed[BATCH_SIZE];
    uint32_t offset, end;
    unsigned rounds;
} cha_ctx;

/// @brief Initialize cha_ctx
/// @param ctx holds ChaCha20 state
/// @param key 32 byte key
/// @param iv 16 bytes, usually the first 4-8 bytes are zeroes, the rest nonce
/// @param rounds ChaCha iteration count: 8=fast, 12=balanced, 20=secure
void cha_init(
  cha_ctx* ctx, const uint8_t* key, const uint8_t* iv, unsigned rounds
) {
    ctx->state[0] = 0x61707865;
    ctx->state[1] = 0x3320646e;
    ctx->state[2] = 0x79622d32;
    ctx->state[3] = 0x6b206574;
    memcpy(ctx->state + 4, key, 32);
    memcpy(ctx->state + 12, iv, 16);
    memset(ctx->unconsumed, 0, sizeof ctx->unconsumed);
    ctx->offset = ctx->end = 0;
    ctx->rounds = rounds;
}

/// Dispose of sensitive data within the context
void cha_wipe(cha_ctx* ctx) { memset(ctx, 0, sizeof(cha_ctx)); }

/// @brief Advance or rewind the stream to any arbitrary location
/// @param ctx ChaCha context
/// @param offset Offset in blocks of 64 bytes (counter change)
void cha_seek_blocks(cha_ctx* ctx, int64_t offset) {
    *(uint64_t*)(ctx->state + 12) += offset;
    ctx->offset = ctx->end = 0;
}

uint64_t cha_generate_batch(
  uint8_t* out, size_t outsize, uint32_t* state, unsigned rounds
) {
#if defined(__x86_64__)
    if (__builtin_cpu_supports("ssse3")) {
        if (__builtin_cpu_supports("avx2")) {
            return _cha_8block(out, outsize, state, rounds);
        }
        return _cha_4block(out, outsize, state, rounds);
    }
#elif defined(__aarch64__)
    return _cha_4block(out, outsize, state);
#endif
    unsigned count = 0;
    unsigned n = _cha_block(out, state, rounds);
    count += n;
    out += n;
    return count;
}

/// @brief Incremental generation, keeps state between calls
/// @param ctx ChaCha context
/// @param out output buffer
/// @param outlen output buffer length
void cha_update(cha_ctx* ctx, uint8_t* out, uint64_t outlen) {
    // The included header will mess with these variables
    uint8_t* end = out + outlen;
    if (ctx->offset) {
        // Need to generate stored buffer?
        if (ctx->end == 0)
            ctx->end = cha_generate_batch(
              ctx->unconsumed, BATCH_SIZE, ctx->state, ctx->rounds
            );
        // Deliver stored bytes first
        uint64_t N = ctx->end - ctx->offset;
        if (N > outlen)
            N = outlen;
        memcpy(out, ctx->unconsumed + ctx->offset, N);
        ctx->offset += N;
        out += N;
        if (out == end)
            return;
    }
    out += cha_generate_batch(out, end - out, ctx->state, ctx->rounds);
    const uint32_t N = end - out;
    if (N) {
        ctx->end = cha_generate_batch(
          ctx->unconsumed, BATCH_SIZE, ctx->state, ctx->rounds
        );
        memcpy(out, ctx->unconsumed, N);
        ctx->offset = N;
    }
}

/// @brief Produce a requested number of random bytes, single shot.
/// @param out output buffer
/// @param outlen output buffer length
/// @param key 32 byte key
/// @param iv 16 bytes, where normally initial 4-8 bytes are 0 (counter)
void cha_generate(
  uint8_t* out, uint64_t outlen, const uint8_t key[32], const uint8_t iv[16]
) {
    cha_ctx ctx;
    cha_init(&ctx, key, iv, 20);
    cha_update(&ctx, out, outlen);
    cha_wipe(&ctx);
}
