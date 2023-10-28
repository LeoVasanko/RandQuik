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

#include "c-stream.h"
#include "u4-stream.h"
#include "u8-stream.h"

void cha_init(cha_ctx* ctx, const uint8_t* key, const uint8_t* iv) {
    ctx->input[0] = 0x61707865;
    ctx->input[1] = 0x3320646e;
    ctx->input[2] = 0x79622d32;
    ctx->input[3] = 0x6b206574;
    memcpy(ctx->input + 4, key, 32);
    memcpy(ctx->input + 12, iv, 16);
}

void cha_wipe(cha_ctx* ctx) { memset(&ctx, 0, sizeof(cha_ctx)); }

int cha_update(cha_ctx* ctx, uint8_t* out, uint64_t outlen) {
    // The included header will mess with these variables
    uint8_t* c = out;
    uint8_t* end = out + outlen;
    // TODO: Handle resume if we are not at block boundary
    if (__builtin_cpu_supports("avx2")) {
        c += _cha_8block(ctx->input, c, end);
        assert(end - c < 512);
        c += _cha_4block(ctx->input, c, end);
        assert(end - c < 256);
    }
    c += _cha_block(ctx->input, c, end);
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
