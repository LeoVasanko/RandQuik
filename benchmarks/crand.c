#include <math.h>
#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    printf("RAND_MAX = %d (%.1lf bit)\n", RAND_MAX, log2(RAND_MAX));
    const uint64_t rounds = 1000000000ull * 8 / (unsigned)log2(RAND_MAX);
    for (uint64_t i = rounds; i-->0;) {
        rand();
    }
}
