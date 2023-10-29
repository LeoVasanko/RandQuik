import secrets
import sys

import cha
import numpy as np


class ChaRandom(np.random.BitGenerator):
    def __init__(self, seed=None):
        super().__init__(seed)
        sys.stderr.write("Construct\n")
        if seed is None:
            key = secrets.token_bytes(32)
        else:
            key = (
                np.random.SeedSequence(seed, pool_size=8)
                .generate_state(4, dtype=np.uint64)
                .tobytes()
            )
        self._generator = cha.Cha(key, bytes(8) + b"NumpyGen")

    def random_raw(self, size=None):
        sys.stderr.write(f"Random raw {size=}\n")
        if size is None:
            return int.from_bytes(self._generator(bytearray(8)), "little")
        ret = np.empty(size, np.uint64)
        self._generator(ret.data)
        return ret

    def spawn(self, n):
        sys.stderr.write(f"Spawn {n=}\n")
        raise NotImplementedError
