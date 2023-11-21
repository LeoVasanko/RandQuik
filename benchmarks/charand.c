#include "chacha20.c"
#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    uint64_t N = 1000000;
    uint8_t* buf = malloc(N);
    const uint8_t key[32] = {0};
    const uint8_t nonce[16] = {0};
    for (uint64_t i = 0; i < 1000; ++i)
    {
        cha_generate(buf, N, key, nonce);
    }
    free(buf);
}
