#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    printf("RAND_MAX = %d\n", RAND_MAX);
    for (unsigned long long i = 0; i < 1000000000; ++i)
    {
        rand();
    }
}
