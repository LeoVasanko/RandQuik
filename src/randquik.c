#ifdef __GNUC__
#pragma GCC target("sse2")
#pragma GCC target("ssse3")
#pragma GCC target("avx2")
#endif

#include "randquik.h"

#include <errno.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <emmintrin.h>
#include <immintrin.h>
#include <tmmintrin.h>
#include <pthread.h>
#include <time.h>
#include <unistd.h>

#define BLOCK_SIZE (1 << 21) // 2 MiB seems optimal for speed

static volatile bool quit = false;

void signal_handler(int sig)
{
    quit = true;
    signal(SIGINT, SIG_DFL);
    signal(SIGTERM, SIG_DFL);
}

static const unsigned char default_iv[16] = "\0\0\0\0\0\0\0\0RandQuik";
typedef struct thread_args
{
    int index;
    int done;
    unsigned char *buf;
    unsigned char key[32];
    unsigned workers;
    pthread_mutex_t lock;
    pthread_cond_t cond;
    pthread_t thread;
} thread_args;

void *producer_thread(void *a)
{
    thread_args *args = (thread_args *)a;
    const unsigned long long ivstep = args->workers * BLOCK_SIZE / 64;
    while (!quit)
    {
        pthread_mutex_lock(&args->lock);
        while (args->done)
        {
            pthread_cond_wait(&args->cond, &args->lock);
        }
        unsigned char iv[16];
        memcpy(iv, default_iv, 16);
        *(uint64_t *)iv += args->index * ivstep; // Counter increment
        chacha20_stream(args->buf, BLOCK_SIZE, args->key, default_iv);
        args->done = 1;
        pthread_cond_signal(&args->cond);
        pthread_mutex_unlock(&args->lock);
    }
    return NULL;
}

void print_status(unsigned long long bytes, unsigned long long max_bytes, struct timespec start_time)
{
    struct timespec end_time;
    clock_gettime(CLOCK_MONOTONIC, &end_time);
    double t = (end_time.tv_sec - start_time.tv_sec) + 1e-9 * (end_time.tv_nsec - start_time.tv_nsec);
    char buf[64] = {};
    double speed = bytes / t;
    char const *unit = "MB";
    double m = 1e-6;
    if (speed > 0.5e9)
    {
        unit = "GB";
        m = 1e-9;
    }
    if (max_bytes)
    {
        snprintf(buf, sizeof buf - 1, " of %'.0lf", m * max_bytes);
    }

    fprintf(stderr, "\r%5.0lf%s %s written, %.2lf %s/s.\e[K", m * bytes, buf, unit, m * speed, unit);
}
int fast(FILE *f, unsigned workers, unsigned long long max_bytes, unsigned char const key[32], unsigned char const iv[16])
{
    thread_args args[workers];
    memset(args, 0, sizeof args);
    for (int i = 0; i < workers; ++i)
    {
        args[i].index = i;
        args[i].buf = malloc(BLOCK_SIZE);
        args[i].workers = workers;
        memcpy(args[i].key, key, 32);
        pthread_mutex_init(&args[i].lock, NULL);
        pthread_cond_init(&args[i].cond, NULL);
        pthread_create(&args[i].thread, NULL, producer_thread, &args[i]);
    }

    struct timespec start_time;
    clock_gettime(CLOCK_MONOTONIC, &start_time);

    int i = -1;
    unsigned long long bytes = 0;
    while (!quit)
    {
        i = (i + 1) % workers;
        pthread_mutex_lock(&args[i].lock);
        while (!args[i].done)
        {
            pthread_cond_wait(&args[i].cond, &args[i].lock);
        }
        if (bytes % (1 << 30) == 0 || bytes + BLOCK_SIZE >= max_bytes)
        {
            print_status(bytes, max_bytes, start_time);
        }
        unsigned long long sz = BLOCK_SIZE;
        if (max_bytes && bytes + sz >= max_bytes)
        {
            fprintf(stderr, "\r\e[KMax reached\n");
            sz = max_bytes - bytes;
            quit = true;
        }
        if (fwrite(args[i].buf, sz, 1, f) != 1)
        {
            quit = true;
            fprintf(stderr, "\r\e[KWrite failed: %s\n", strerror(errno));
        }
        bytes += sz;
        args[i].done = 0;
        pthread_cond_signal(&args[i].cond);
        pthread_mutex_unlock(&args[i].lock);
    }

    print_status(bytes, max_bytes, start_time);
    for (int i = 0; i < workers; ++i)
    {
        args[i].done = 0;
        pthread_cancel(args[i].thread);
        pthread_join(args[i].thread, NULL);
        pthread_mutex_destroy(&args[i].lock);
        pthread_cond_destroy(&args[i].cond);
        free(args[i].buf);
    }
    fprintf(stderr, "\nRandQuik wrote %llu bytes!\n\n", bytes);
    return 0;
}

bool parse_hex(char *str, unsigned char *buf, size_t len)
{
    for (size_t i = 0; i < len; ++i)
    {
        int sz = 0;
        if (sscanf(str, "%2hhx%n", buf + i, &sz) != 1)
        {
            if (*str)
            {
                fprintf(stderr, "Unable to read seed at `%s`\n\n", str);
                return false;
            }
            return true; // Shorter than key length is OK
        }
        str += sz;
    }
    return true;
}

void print_hex(unsigned char *buf, size_t len)
{
    for (size_t i = 0; i < len; ++i)
    {
        fprintf(stderr, "%02hhx", buf[i]);
    }
}

void help(char **argv)
{
    fprintf(stderr, "Usage: %s [-t #threads] [-s hexseed] [-b #bytes] [-o outputfile]\n\n", argv[0]);
}

int main(int argc, char **argv)
{
    unsigned char key[32] = {};
    unsigned char iv[16] = {};
    unsigned int workers = 8;
    char *output = NULL;
    unsigned long long max_bytes = 0;
    bool seeded = false;
    for (char opt; (opt = getopt(argc, argv, "bost")) != -1;)
    {
        if (opt == 't')
        {
            if (optind >= argc || sscanf(argv[optind++], "%u", &workers) != 1)
            {
                fprintf(stderr, "Expected the number of worker threads after -t\n");
                exit(EXIT_FAILURE);
            }
            continue;
        }
        if (opt == 's')
        {
            if (optind >= argc || !parse_hex(argv[optind++], key, 32))
            {
                fprintf(stderr, "Expected a hex seed string after -s\n");
                exit(EXIT_FAILURE);
            }
            seeded = true;
            continue;
        }
        if (opt == 'o')
        {
            if (optind >= argc)
            {
                fprintf(stderr, "Expected output filename after -s\n");
                return 1;
            }
            if (strcmp(argv[optind], "-") != 0)
            {
                output = argv[optind++];
            }
            continue;
        }
        if (opt == 'b')
        {
            if (optind >= argc || sscanf(argv[optind++], "%llu", &max_bytes) != 1)
            {
                fprintf(stderr, "Expected a maximum number of bytes to read after -b\n");
                exit(EXIT_FAILURE);
            }
            continue;
        }
        help(argv);
        return 1;
    }
    FILE *f = stdout;
    if (output)
    {
        f = fopen(output, "wb");
        if (!f)
        {
            fprintf(stderr, "Failed to open %s for writing.\n", output);
            return 1;
        }
    }
    else if (isatty(1))
    {
        fprintf(stderr, "Won't print random on console. Pipe me to another program or file instead.\n\n");
        help(argv);
        return 1;
    }
    if (!seeded)
    {
        FILE *urand = fopen("/dev/urandom", "rb");
        if (!urand || fread(key, 32, 1, urand) != 1)
        {
            fprintf(stderr, "Failed to seed from /dev/urandom. Use -s hexstring for manual seeding.\n");
            fclose(urand);
            return 1;
        }
        fclose(urand);
        fprintf(stderr, "Random seed generated. This sequence may be repeated by:\n%s -s ", argv[0]);
        print_hex(key, 32);
        fprintf(stderr, "\n\n");
    }
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    int ret = fast(f, workers, max_bytes, key, iv);
    fclose(f);
    return ret;
}

typedef struct chacha_ctx
{
    uint32_t input[16];
} chacha_ctx;

static void
chacha_init(chacha_ctx *ctx, const uint8_t *k, const uint8_t *iv)
{
    ctx->input[0] = 0x61707865;
    ctx->input[1] = 0x3320646e;
    ctx->input[2] = 0x79622d32;
    ctx->input[3] = 0x6b206574;
    memcpy(ctx->input + 4, k, 32);
    memcpy(ctx->input + 12, iv, 16);
}

int chacha20_stream(unsigned char *out, unsigned long long outlen,
                    const unsigned char key[32], const unsigned char iv[16])
{
    chacha_ctx ctx;
    chacha_init(&ctx, key, iv);
    {
        // The included header will mess with these variables
        unsigned long long bytes = outlen;
        uint32_t *x = ctx.input;
        unsigned char *c = out;
        if (__builtin_cpu_supports("avx2"))
        {
#include "u8-stream.h"
#include "u4-stream.h"
        }
#include "c-stream.h"
    }
    memset(&ctx, 0, sizeof ctx);
    return 0;
}
