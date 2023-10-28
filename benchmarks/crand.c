#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    printf("RAND_MAX = %d\n", RAND_MAX);
    for (uint64_t i = 0; i < 1000000000; ++i)
    {
        rand();
    }
}
