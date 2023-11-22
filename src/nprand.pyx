#cython: language_level=3

from libc.stdint cimport uint32_t, uint8_t, uint64_t
from cpython.pycapsule cimport PyCapsule_IsValid, PyCapsule_GetPointer

import numpy as np
cimport numpy as np
cimport cython
import secrets

from numpy.random cimport BitGenerator

np.import_array()

cdef extern from "npbitgen.h":
    struct cha_ctx:
        uint32_t state[16]
        uint8_t unconsumed[64]
        uint8_t uncount

    void cha_init(cha_ctx* ctx, const uint8_t* key, const uint8_t* iv) nogil
    uint64_t cha_uint64(void *state) nogil
    uint32_t cha_uint32(void *state) nogil
    double cha_double(void *state) nogil

cdef class Cha(BitGenerator):

    cdef cha_ctx rng_state

    def __init__(self, seed=None):
        BitGenerator.__init__(self, seed)
        self._bitgen.state = <void *>&self.rng_state
        self._bitgen.next_uint64 = &cha_uint64
        self._bitgen.next_uint32 = &cha_uint32
        self._bitgen.next_double = &cha_double
        self._bitgen.next_raw = &cha_uint64
        # Generated state is ChaCha20 key
        key = self._seed_seq.generate_state(4, np.uint64)
        cha_init(&self.rng_state, <uint8_t *>np.PyArray_DATA(key), b"NumpRand")
