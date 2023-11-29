#include "chacha20.h"

static uint64_t cha_uint64(void* st) {
    cha_ctx* ctx = (cha_ctx*)st;
    if (ctx->offset == ctx->end) {
        ctx->offset = 0;
        ctx->end =
          ctx->gen(ctx->unconsumed, BATCH_SIZE, ctx->state, ctx->rounds);
    }
    uint64_t ret = *(uint64_t*)(ctx->unconsumed + ctx->offset);
    ctx->offset += sizeof(uint64_t);
    return ret;
}
static uint32_t cha_uint32(void* st) { return cha_uint64(st); }
static double cha_double(void* st) {
    return cha_uint64(st) / (UINT64_MAX + 1.0);
}
