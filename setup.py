import os
from distutils.core import setup

import numpy
from Cython.Build import cythonize
from setuptools import Extension

os.environ["CFLAGS"] = "-O3 -march=native -Wall -Wextra"
extensions = [
    Extension(
        "nprand",
        ["src/nprand.pyx"],
        include_dirs=[numpy.get_include()],
        define_macros=[("NPY_NO_DEPRECATED_API", "NPY_1_7_API_VERSION")],
    )
]
setup(ext_modules=cythonize(extensions))
