
from setuptools import setup, Extension
from Cython.Build import cythonize

setup(
    ext_modules=cythonize(
        [Extension("sum_squares", ["sum_squares.pyx"])],
        compiler_directives={"language_level": "3"},
    )
)
