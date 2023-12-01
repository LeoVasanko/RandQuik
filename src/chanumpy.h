#include "charandom.h"

static uint64_t cha_uint64(void* st) {
    cha_ctx* ctx = (cha_ctx*)st;
    if (ctx->offset + sizeof(uint64_t) > ctx->end) {
        ctx->offset -= ctx->end;
        ctx->end =
          ctx->gen(ctx->unconsumed, BATCH_SIZE, ctx->state, ctx->rounds);
    }
    uint64_t ret = *(uint64_t*)(ctx->unconsumed + ctx->offset);
    ctx->offset += sizeof(uint64_t);
    return ret;
}
static uint32_t cha_uint32(void* st) { return cha_uint64(st); }
static double cha_double(void* st) {
    // Fast uint64_to_double conversion from numpy/random/_common.pxd
    return (cha_uint64(st) >> 11) * (1.0 / 9007199254740992.0);
}
