#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "charandom.h"

static volatile bool quit = false;

void signal_handler(int sig) {
    quit = true;
    signal(SIGINT, SIG_DFL);
    signal(SIGTERM, SIG_DFL);
}

#define BLOCK_SIZE (1 << 21) // 2 MiB seems optimal for speed

static const unsigned char default_iv[16] = "\0\0\0\0\0\0\0\0RandQuik";
typedef struct thread_args {
    int index;
    int done;
    unsigned char* buf;
    unsigned char key[32];
    unsigned workers;
    unsigned rounds;
    pthread_mutex_t lock;
    pthread_cond_t cond;
    pthread_t thread;
} thread_args;

void* producer_thread(void* a) {
    thread_args* args = (thread_args*)a;
    const uint64_t ivstep = args->workers * BATCH_BLOCKS;
    cha_ctx ctx;
    cha_init(&ctx, args->key, default_iv, args->rounds);
    cha_seek_blocks(&ctx, args->index * BLOCK_SIZE / 64);
    while (!quit) {
        pthread_mutex_lock(&args->lock);
        while (args->done) {
            pthread_cond_wait(&args->cond, &args->lock);
        }
        cha_update(&ctx, args->buf, BLOCK_SIZE);
        cha_seek_blocks(&ctx, ivstep);
        args->done = 1;
        pthread_cond_signal(&args->cond);
        pthread_mutex_unlock(&args->lock);
    }
    cha_wipe(&ctx);
    return NULL;
}

void print_status(
  uint64_t bytes, uint64_t max_bytes, struct timespec start_time
) {
    struct timespec end_time;
    clock_gettime(CLOCK_MONOTONIC, &end_time);
    double t = (end_time.tv_sec - start_time.tv_sec) +
               1e-9 * (end_time.tv_nsec - start_time.tv_nsec);
    char buf[64] = {};
    double speed = bytes / t;
    char const* unit = "MB";
    double m = 1e-6;
    if (speed > 0.5e9) {
        unit = "GB";
        m = 1e-9;
    }
    if (max_bytes) {
        snprintf(buf, sizeof buf - 1, " of %'.0lf", m * max_bytes);
    }

    fprintf(
      stderr, "\r%5.0lf%s %s written, %.2lf %s/s.\e[K", m * bytes, buf, unit,
      m * speed, unit
    );
}

int fast(
  FILE* f, unsigned workers, uint64_t max_bytes, unsigned char const key[32],
  unsigned char const iv[16], unsigned rounds
) {
    thread_args args[workers];
    memset(args, 0, sizeof args);
    for (int i = 0; i < workers; ++i) {
        args[i].index = i;
        args[i].buf = malloc(BLOCK_SIZE);
        args[i].workers = workers;
        args[i].rounds = rounds;
        memcpy(args[i].key, key, 32);
        pthread_mutex_init(&args[i].lock, NULL);
        pthread_cond_init(&args[i].cond, NULL);
        pthread_create(&args[i].thread, NULL, producer_thread, &args[i]);
    }

    struct timespec start_time;
    clock_gettime(CLOCK_MONOTONIC, &start_time);

    int i = -1;
    uint64_t bytes = 0;
    while (!quit) {
        i = (i + 1) % workers;
        pthread_mutex_lock(&args[i].lock);
        while (!args[i].done) {
            pthread_cond_wait(&args[i].cond, &args[i].lock);
        }
        if (bytes % (1 << 30) == 0 || bytes + BLOCK_SIZE >= max_bytes) {
            print_status(bytes, max_bytes, start_time);
        }
        uint64_t sz = BLOCK_SIZE;
        if (max_bytes && bytes + sz >= max_bytes) {
            fprintf(stderr, "\r\e[KMax reached\n");
            sz = max_bytes - bytes;
            quit = true;
        }
        if (fwrite(args[i].buf, sz, 1, f) != 1) {
            quit = true;
            fprintf(stderr, "\r\e[KWrite failed: %s\n", strerror(errno));
        }
        bytes += sz;
        args[i].done = 0;
        pthread_cond_signal(&args[i].cond);
        pthread_mutex_unlock(&args[i].lock);
    }

    print_status(bytes, max_bytes, start_time);
    for (int i = 0; i < workers; ++i) {
        args[i].done = 0;
        pthread_cancel(args[i].thread);
        pthread_join(args[i].thread, NULL);
        pthread_mutex_destroy(&args[i].lock);
        pthread_cond_destroy(&args[i].cond);
        free(args[i].buf);
    }
    fprintf(stderr, "\nRandQuik wrote %" PRIu64 " bytes!\n\n", bytes);
    return 0;
}

bool parse_hex(char* str, unsigned char* buf, size_t len) {
    for (size_t i = 0; i < len; ++i) {
        int sz = 0;
        if (sscanf(str, "%2hhx%n", buf + i, &sz) != 1) {
            if (*str) {
                fprintf(stderr, "Unable to read seed at `%s`\n\n", str);
                return false;
            }
            return true; // Shorter than key length is OK
        }
        str += sz;
    }
    return true;
}

void print_hex(unsigned char* buf, size_t len) {
    for (size_t i = 0; i < len; ++i) {
        fprintf(stderr, "%02hhx", buf[i]);
    }
}

void help(char** argv) {
    fprintf(
      stderr,
      "Usage: %s [-t #threads] [-s hexseed] [-b #bytes] [-r #rounds] [-o "
      "outputfile]\n\n",
      argv[0]
    );
}

int main(int argc, char** argv) {
    unsigned char key[32] = {};
    unsigned char iv[16] = {};
    unsigned int workers = 8;
    unsigned int rounds = 20;
    char* output = NULL;
    uint64_t max_bytes = 0;
    bool seeded = false;
    for (char opt; (opt = getopt(argc, argv, "bostr")) != -1;) {
        if (opt == 't') {
            if (optind >= argc || sscanf(argv[optind++], "%u", &workers) != 1) {
                fprintf(
                  stderr, "Expected the number of worker threads after -t\n"
                );
                return 1;
            }
            continue;
        }
        if (opt == 'r') {
            if (optind >= argc || sscanf(argv[optind++], "%u", &rounds) != 1) {
                fprintf(
                  stderr,
                  "Expected the number ChaCha rounds (8, 12 or 20) after -r\n"
                );
                return 1;
            }
            continue;
        }
        if (opt == 's') {
            if (optind >= argc || !parse_hex(argv[optind++], key, 32)) {
                fprintf(stderr, "Expected a hex seed string after -s\n");
                return 1;
            }
            seeded = true;
            continue;
        }
        if (opt == 'o') {
            if (optind >= argc) {
                fprintf(stderr, "Expected output filename after -s\n");
                return 1;
            }
            if (strcmp(argv[optind], "-") != 0) {
                output = argv[optind++];
            }
            continue;
        }
        if (opt == 'b') {
            char unit[16] = {};
            if (optind >= argc || sscanf(argv[optind++], "%" SCNu64 "%15s", &max_bytes, unit) < 1) {
                fprintf(
                  stderr,
                  "Expected a maximum number of bytes to read after -b\n"
                );
                return 1;
            }
            if (strcasecmp(unit, "k") == 0 || strcasecmp(unit, "kb") == 0)
                max_bytes *= 1000ull;
            else if (strcasecmp(unit, "m") == 0 || strcasecmp(unit, "mb") == 0)
                max_bytes *= 1000000ull;
            else if (strcasecmp(unit, "g") == 0 || strcasecmp(unit, "gb") == 0)
                max_bytes *= 1000000000ull;
            else if (strcasecmp(unit, "t") == 0 || strcasecmp(unit, "tb") == 0)
                max_bytes *= 1000000000000ull;
            else if (strcasecmp(unit, "ki") == 0 || strcasecmp(unit, "kib") == 0)
                max_bytes <<= 10;
            else if (strcasecmp(unit, "mi") == 0 || strcasecmp(unit, "mib") == 0)
                max_bytes <<= 20;
            else if (strcasecmp(unit, "gi") == 0 || strcasecmp(unit, "gib") == 0)
                max_bytes <<= 30;
            else if (strcasecmp(unit, "ti") == 0 || strcasecmp(unit, "tib") == 0)
                max_bytes <<= 40;
            continue;
        }
        help(argv);
        return 1;
    }
    FILE* f = stdout;
    if (output) {
        f = fopen(output, "wb");
        if (!f) {
            fprintf(stderr, "Failed to open %s for writing.\n", output);
            return 1;
        }
    } else if (isatty(1)) {
        fprintf(
          stderr,
          "Won't print random on console. Pipe me to another program or "
          "file instead.\n\n"
        );
        help(argv);
        return 1;
    }
    if (!seeded) {
        FILE* urand = fopen("/dev/urandom", "rb");
        if (!urand || fread(key, 32, 1, urand) != 1) {
            fprintf(
              stderr, "Failed to seed from /dev/urandom. Use -s hexstring for "
                      "manual seeding.\n"
            );
            fclose(urand);
            return 1;
        }
        fclose(urand);
        fprintf(
          stderr,
          "Random seed generated. This sequence may be repeated by:\n%s ",
          argv[0]
        );
        if (rounds != 20)
            fprintf(stderr, "-r %u -s ", rounds);
        else
            fprintf(stderr, "-s ");

        print_hex(key, 32);
        fprintf(stderr, "\n\n");
    }
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    int ret = fast(f, workers, max_bytes, key, iv, rounds);
    fclose(f);
    return ret;
}
