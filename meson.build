project('randquik', 'c')
executable(
    'randquik',
    'src/cli.c',
    c_args: ['-Wall', '-O3', '-march=native'],
    install: true,
)
dependency('threads')

library(
    'randquik-chacha20',
    'src/chacha20.c',
    build_by_default: true,
    c_args: ['-Wall', '-O3', '-march=native'],
)
