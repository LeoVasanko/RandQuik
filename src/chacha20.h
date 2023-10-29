#pragma once
#include <stdbool.h>
#include <stdint.h>

static const uint64_t CHA_BLOCK_SIZE = 64;

typedef struct cha_ctx {
    uint32_t state[16];
    uint8_t unconsumed[64];
    uint8_t uncount;
} cha_ctx;

/// @brief Initialize cha_ctx
/// @param ctx holds ChaCha20 state
/// @param key 32 byte key
/// @param iv 16 bytes, where normally initial 4-8 bytes are zeroes and the rest
/// nonce
void cha_init(cha_ctx* ctx, const uint8_t* key, const uint8_t* iv);

/// Dispose of sensitive data within the context
void cha_wipe(cha_ctx* ctx);

/// @brief Incremental upgrade
/// @param ctx Gets updated
/// @param out
/// @param outlen
/// @return
int cha_update(cha_ctx* ctx, uint8_t* out, uint64_t outlen);

/// @brief Produce a requested number of random bytes of the stream.
/// @param out
/// @param outlen
/// @param key
/// @param iv
/// @return
int cha_generate(
  uint8_t* out, uint64_t outlen, const uint8_t key[32], const uint8_t iv[16]
);
