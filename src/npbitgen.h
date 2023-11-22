#include "chacha20.h"


static uint64_t cha_uint64(void *st) {
    cha_ctx *ctx = (cha_ctx *)st;
    uint64_t ret;
    cha_update(ctx, (uint8_t *)&ret, sizeof ret);
    return ret;
}
static uint32_t cha_uint32(void *st) {
    cha_ctx *ctx = (cha_ctx *)st;
    uint32_t ret;
    cha_update(ctx, (uint8_t *)&ret, sizeof ret);
    return ret;

}
static double cha_double(void *st) {
    return cha_uint64(st) / (UINT64_MAX + 1.0);
}
